import json
import logging

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    signup_coupon_issued = fields.Boolean(
        string='Sign-up Coupon Issued',
        copy=False,
        help='The account was activated by the email code (or Google / Facebook): '
             'it may use the sign-up coupon (once).',
    )

    def _create_user_from_template(self, values):
        user = super()._create_user_from_template(values)
        if self.env.context.get('signup_coupon_issue'):
            user.signup_coupon_issued = True
        return user

    @api.model
    def _signup_find_account(self, email):
        """The account of an email (its login or its customer's email), archived ones included.
        :param str email: normalized email"""
        if not email:
            return self.browse()
        Users = self.sudo().with_context(active_test=False)
        return Users.search(Domain.OR([
            Users._get_login_domain(email),
            Domain('login', '=ilike', email),
            Domain('partner_id.email_normalized', '=', email),
        ]), order='active desc, id', limit=1)

    def _signup_email_proven(self):
        """The owner proved the email: the code at sign-up, or Google / Facebook."""
        self.ensure_one()
        return bool(self.sudo().signup_coupon_issued or self.sudo().oauth_uid)

    @api.model
    def _signup_verification_on(self):
        websites = self.env['website'].sudo().search([('signup_verification', '=', True)], limit=1)
        return bool(websites)

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        """Google / Facebook (Annex 3A task 3): no code, the provider verified the
        email. A guest email gets its account on its customer record; an email
        with an account gets the provider added to it (instead of "Access denied")."""
        oauth_uid = validation['user_id']
        if (
            self.env.context.get('no_user_creation')
            or not self._signup_verification_on()
            or self.search_count([('oauth_uid', '=', oauth_uid), ('oauth_provider_id', '=', provider)])
            or json.loads(params['state']).get('t')  # invitation link: standard flow
        ):
            return super()._auth_oauth_signin(provider, validation, params)
        email = email_normalize(validation.get('email') or '')
        if not email:
            return super()._auth_oauth_signin(provider, validation, params)

        account = self._signup_find_account(email)
        if account:
            # Only an email the provider says is verified (Facebook only gives confirmed ones)
            verified = validation.get('email_verified', True)
            if not account.active or str(verified).lower() not in ('true', '1'):
                return super()._auth_oauth_signin(provider, validation, params)
            account.sudo().write({
                'oauth_provider_id': provider,
                'oauth_uid': oauth_uid,
                'oauth_access_token': params['access_token'],
            })
            _logger.info("Sign-in provider %s added to the account %s (same email)", provider, account.login)
            return account.login

        self.env['res.partner']._signup_claim_cart_record(email)
        records = self.env['res.partner']._signup_guest_records(email)
        values = self._generate_signup_values(provider, validation, params)
        values.update(login=email, email=email)
        if records:
            values['partner_id'] = records[0].id
            values.pop('name', None)
        login, _password = self.with_context(signup_coupon_issue=True).signup(values)
        if records:
            records[1:]._signup_flag_duplicates(records[0])
        return login
