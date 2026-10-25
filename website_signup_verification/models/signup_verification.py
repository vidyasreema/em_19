import logging
import secrets
from datetime import timedelta
from email.utils import formataddr

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import consteq
from odoo.tools.misc import hmac

from odoo.addons.auth_signup.models.res_users import SignupError

_logger = logging.getLogger(__name__)

CODE_VALID_MINUTES = 10
MAX_ATTEMPTS = 5
RESEND_SECONDS = 60
MAX_SENDS = 5


class WebsiteSignupVerification(models.TransientModel):
    """A sign-up waiting for its email code (Annex 3A tasks 1, 2 and 5.1):
    nothing is created, linked or activated before the code is entered."""
    _name = 'website.signup.verification'
    _description = 'Sign-up Verification Code'
    _transient_max_hours = 2.0

    website_id = fields.Many2one('website', required=True, ondelete='cascade')
    email = fields.Char(required=True, help='Normalized email: the login of the account')
    name = fields.Char()
    password_hash = fields.Char(help='Password chosen on the sign-up form (encrypted). '
                                     'Empty: the password is chosen with the code.')
    redirect = fields.Char()
    lang = fields.Char()
    email_from = fields.Char()
    code_hash = fields.Char()
    code_expiry = fields.Datetime()
    code_sent_at = fields.Datetime()
    send_count = fields.Integer()
    attempts = fields.Integer()

    @api.model
    def _start(self, website, email, name='', password=None, redirect=''):
        """New sign-up waiting for its code; the code is sent."""
        company = website.sudo().company_id  # visitors may not read the email domain
        domain = company.alias_domain_id.name
        email_from = formataddr((website.name, 'no-reply@%s' % domain)) if domain else company.email_formatted
        verification = self.sudo().create({
            'website_id': website.id,
            'email': email,
            'name': (name or '').strip(),
            'password_hash': self.env['res.users']._crypt_context().hash(password) if password else False,
            'redirect': redirect if redirect and redirect.startswith('/') and not redirect.startswith('//') else '',
            'lang': self.env.context.get('lang'),
            'email_from': email_from,
        })
        verification._send_code()
        return verification

    def _resend_wait(self):
        """Seconds before a new code may be sent (0: now)."""
        self.ensure_one()
        if not self.code_sent_at:
            return 0
        ready_at = self.code_sent_at + timedelta(seconds=RESEND_SECONDS)
        return max(int((ready_at - fields.Datetime.now()).total_seconds()), 0)

    def _can_resend(self):
        self.ensure_one()
        return self.send_count < MAX_SENDS and not self._resend_wait()

    def _send_code(self):
        """A new code replaces the previous one (the counter of tries starts over)."""
        self.ensure_one()
        code = '%06d' % secrets.randbelow(10 ** 6)
        now = fields.Datetime.now()
        self.write({
            'code_hash': self._hash_code(code),
            'code_expiry': now + timedelta(minutes=CODE_VALID_MINUTES),
            'code_sent_at': now,
            'send_count': self.send_count + 1,
            'attempts': 0,
        })
        template = self.env.ref('website_signup_verification.mail_template_signup_code')
        # A failed email stays in Settings > Technical > Emails and is retried by the mail queue
        template.sudo().with_context(code=code, valid_minutes=CODE_VALID_MINUTES).send_mail(self.id, force_send=True)

    def _hash_code(self, code):
        return hmac(self.env(su=True), 'website-signup-verification', '%s:%s' % (self.id, code))

    def _check_code(self, code):
        """:return: an error message, or '' when the code is right"""
        self.ensure_one()
        code = ''.join(ch for ch in (code or '') if ch.isdigit())
        if not code:
            return _("Enter the 6-digit code from the email.")
        if not self.code_hash or self.code_expiry < fields.Datetime.now():
            return _("This code has expired. Ask for a new one.")
        if self.attempts >= MAX_ATTEMPTS:
            return _("Too many wrong codes. Ask for a new one.")
        self.attempts += 1
        if not consteq(self._hash_code(code), self.code_hash):
            return _("This code is not right. Check the email and try again.")
        return ''

    def _complete(self, password=None):
        """Create the account once the code is right: on the most recent guest
        record of the email (its orders and addresses), else on a new one.
        :param str password: chosen with the code (when the form did not ask it)
        :return: res.users"""
        self.ensure_one()
        Users = self.env['res.users'].sudo()
        if Users._signup_find_account(self.email):
            raise UserError(_("You already have an account. Sign in or reset your password."))
        records = self.env['res.partner']._signup_guest_records(self.email)
        values = {'login': self.email, 'email': self.email}
        if records:
            values['partner_id'] = records[0].id
        else:
            values['name'] = self.name or self.email.split('@')[0]
        if self.lang:
            values['lang'] = self.lang
        try:
            user = Users.with_context(signup_coupon_issue=True)._signup_create_user(values)
        except SignupError:
            _logger.exception("Sign-up of %s failed", self.email)
            raise UserError(_("We could not create your account. Please try again."))
        if password:
            user.password = password
        elif self.password_hash:
            Users._set_encrypted_password(user.id, self.password_hash)
        records[1:]._signup_flag_duplicates(user.partner_id)
        self.unlink()
        return user
