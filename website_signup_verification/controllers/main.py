import logging

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request, route
from odoo.tools import email_normalize

from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.website_purchase_journey.controllers.order import JourneyCheckout, journey_apply_code

_logger = logging.getLogger(__name__)

SESSION_VERIFICATION = 'signup_verification_id'
SESSION_SIGNUP_COUPON = 'signup_coupon_applied'
VERIFY_PATH = '/web/signup/verify'


def current_verification():
    """The sign-up of this visitor waiting for its code (empty when none or expired)."""
    verification_id = request.session.get(SESSION_VERIFICATION)
    Verification = request.env['website.signup.verification'].sudo()
    if not verification_id:
        return Verification
    verification = Verification.browse(verification_id).exists()
    return verification.filtered(lambda v: v.website_id == request.website)


def start_verification(email, name='', password=None, redirect=''):
    verification = request.env['website.signup.verification'].sudo()._start(
        request.website, email, name=name, password=password, redirect=redirect)
    request.session[SESSION_VERIFICATION] = verification.id
    return verification


class SignupVerificationHome(AuthSignupHome):

    @http.route()
    def web_auth_signup(self, *args, **kw):
        """Sign-up form (Annex 3A task 1): an email with an account gets the
        sign-in message; otherwise the code is sent and nothing is created yet."""
        if not (request.website.signup_verification and request.httprequest.method == 'POST'):
            return super().web_auth_signup(*args, **kw)
        qcontext = self.get_auth_signup_qcontext()
        if qcontext.get('token') or 'error' in qcontext or not qcontext.get('signup_enabled'):
            return super().web_auth_signup(*args, **kw)

        Users = request.env['res.users'].sudo()
        try:
            values = self._prepare_signup_values(qcontext)
            email = email_normalize(values.get('login') or '')
            if not email:
                raise UserError(_("Enter a valid email address."))
            if not (values.get('name') or '').strip():
                raise UserError(_("Enter your name."))
            if not values.get('password'):
                raise UserError(_("Choose a password."))
            if hasattr(Users, '_check_password_policy'):
                Users._check_password_policy([values['password']])
            if Users._signup_find_account(email):
                qcontext['signup_account_exists'] = email
                return self._signup_render(qcontext)
            start_verification(email, name=values['name'], password=values['password'],
                               redirect=qcontext.get('redirect') or '')
        except UserError as e:
            qcontext['error'] = e.args[0]
            return self._signup_render(qcontext)
        return request.redirect(VERIFY_PATH)

    def _signup_render(self, qcontext):
        response = request.render('auth_signup.signup', qcontext)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response

    @route(VERIFY_PATH, type='http', auth='public', website=True, sitemap=False, methods=['GET', 'POST'])
    def web_signup_verify(self, code='', password='', confirm_password='', **kw):
        """Enter the code (Annex 3A task 2); the account is created only then."""
        verification = current_verification()
        if not verification:
            return request.render('website_signup_verification.signup_verify', {'expired': True})
        ask_password = not verification.password_hash
        error = ''
        if request.httprequest.method == 'POST':
            if ask_password and not password:
                error = _("Choose a password.")
            elif ask_password and password != confirm_password:
                error = _("Passwords do not match; please retype them.")
            error = error or verification._check_code(code)
            if not error:
                redirect = verification.redirect
                try:
                    if ask_password and hasattr(verification.env['res.users'], '_check_password_policy'):
                        verification.env['res.users']._check_password_policy([password])
                    user = verification._complete(password=password if ask_password else None)
                except UserError as e:
                    error = e.args[0]
                else:
                    request.session.pop(SESSION_VERIFICATION, None)
                    self._signup_log_in(user)
                    # Like the standard sign-up: the "account created" email
                    template = request.env.ref('auth_signup.mail_template_user_signup_account_created',
                                               raise_if_not_found=False)
                    if template:
                        template.sudo().send_mail(user.id, force_send=True)
                    return request.redirect(redirect or '/my')
        return request.render('website_signup_verification.signup_verify', {
            'verification': verification,
            'ask_password': ask_password,
            'error': error,
            'sent': kw.get('sent'),
            'resend_wait': verification._resend_wait(),
            'can_resend': verification._can_resend(),
        })

    @route(VERIFY_PATH + '/resend', type='http', auth='public', website=True, sitemap=False, methods=['POST'])
    def web_signup_verify_resend(self, **kw):
        verification = current_verification()
        if verification and verification._can_resend():
            verification._send_code()
            return request.redirect(VERIFY_PATH + '?sent=1')
        return request.redirect(VERIFY_PATH)

    def _signup_log_in(self, user):
        """Sign the new customer in: the email code proved the email is theirs."""
        session = request.session
        session['pre_login'] = user.login
        session['pre_uid'] = user.id
        session.finalize(request.env)
        request.update_env(user=user.id)
        user._update_last_login()


class SignupVerificationCheckout(JourneyCheckout):

    @route()
    def journey_order_signup(self, **post):
        """"Create my account" on the confirmation page: the code goes to the
        email of the order; the password is chosen with the code."""
        if not request.website.signup_verification:
            return super().journey_order_signup(**post)
        order_id = request.session.get('sale_last_order_id')
        order_sudo = request.env['sale.order'].sudo().browse(order_id).exists() if order_id else None
        if not order_sudo or not request.env.user._is_public() or not order_sudo._journey_can_sign_up():
            return request.redirect('/shop/confirmation')
        partner = order_sudo.partner_id
        start_verification(partner.email_normalized, name=partner.name, redirect='/my/orders/%s' % order_sudo.id)
        return request.redirect(VERIFY_PATH)

    def _journey_apply_welcome_coupon(self, order_sudo):
        """After signing up, the sign-up coupon (fixed code) is applied to the
        cart once, instead of the welcome coupon (kept for the next order).
        Accounts without it (or once it is used) keep the welcome coupon."""
        code = request.website._signup_coupon_code()
        user = request.env.user
        if not code or user._is_public() or not user.sudo().signup_coupon_issued:
            return super()._journey_apply_welcome_coupon(order_sudo)
        if request.session.get(SESSION_SIGNUP_COUPON):
            return
        request.session[SESSION_SIGNUP_COUPON] = True
        if order_sudo.code_enabled_rule_ids.filtered(lambda r: r.code == code):
            return
        error = journey_apply_code(order_sudo, code)
        if error:
            _logger.info("Sign-up coupon not applied to %s: %s", order_sudo.name, error)
            super()._journey_apply_welcome_coupon(order_sudo)
