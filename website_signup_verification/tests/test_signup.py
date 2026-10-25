import json
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields, http
from odoo.exceptions import AccessDenied
from odoo.http import root
from odoo.tests import new_test_user, tagged

from odoo.addons.mail.tests.common import MockEmail
from odoo.addons.website_purchase_journey.tests.test_order import OrderCommon

CODE = 123456
RANDBELOW = 'odoo.addons.website_signup_verification.models.signup_verification.secrets.randbelow'


class SignupCommon(OrderCommon, MockEmail):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website.write({
            'auth_signup_uninvited': 'b2c',
            'signup_verification': True,
            'signup_coupon_program_id': cls.env.ref('website_signup_verification.loyalty_program_signup_coupon').id,
        })
        cls.env['ir.config_parameter'].sudo().set_param('auth_signup.invitation_scope', 'b2c')
        # Like the live company: the code is sent from no-reply@ of its email domain
        cls.env.company.alias_domain_id = cls.env['mail.alias.domain'].create({'name': 'thecut.test'})
        cls.Users = cls.env['res.users'].with_context(active_test=False)
        cls.Verification = cls.env['website.signup.verification'].sudo()

    def _csrf(self):
        return http.Request.csrf_token(self)

    def _sign_up(self, email, name='Sara Test', password='Sup3r-secret!', confirm=None, redirect=''):
        with patch(RANDBELOW, return_value=CODE):
            return self.url_open('/web/signup', data={
                'csrf_token': self._csrf(), 'name': name, 'login': email,
                'password': password, 'confirm_password': confirm or password, 'redirect': redirect,
            })

    def _verify(self, code=CODE, **values):
        return self.url_open('/web/signup/verify', data={'csrf_token': self._csrf(), 'code': str(code), **values})

    def _guest(self, email, name='Guest', order_date=None):
        partner = self._address(24.4539, 54.3773, name=name, email=email)
        order = self._order(420, self.island, partner)
        order.action_confirm()
        if order_date:
            order.date_order = order_date
        return partner, order

    def _session_uid(self):
        return root.session_store.get(self.opener.cookies['session_id']).uid


@tagged('post_install', '-at_install')
class TestSignupCode(SignupCommon):
    """Annex 3A tasks 1, 2 and 4."""

    def setUp(self):
        super().setUp()
        self.authenticate(None, None)

    def test_new_email(self):
        """1.4 + 2: the code is sent and the account exists only once it is entered."""
        response = self._sign_up('new.customer@example.com', redirect='/shop/order')
        self.assertTrue(response.url.endswith('/web/signup/verify'))
        self.assertIn('new.customer@example.com', response.text)
        self.assertFalse(self.Users.search([('login', '=', 'new.customer@example.com')]), "no account before the code")

        response = self._verify(code=654321)
        self.assertIn('This code is not right', response.text)
        self.assertFalse(self.Users.search([('login', '=', 'new.customer@example.com')]), "a wrong code activates nothing")

        response = self._verify()
        user = self.Users.search([('login', '=', 'new.customer@example.com')])
        self.assertTrue(user.active and user._is_portal())
        self.assertEqual(user.name, 'Sara Test')
        self.assertTrue(user.signup_coupon_issued)
        self.assertEqual(self._session_uid(), user.id, "signed in")
        self.assertIn('/shop/order', response.url)
        # The password of the sign-up form is the account's
        self.authenticate('new.customer@example.com', 'Sup3r-secret!')
        self.assertFalse(self.Verification.search([('email', '=', 'new.customer@example.com')]), "the code is used up")

    def test_guest_email_is_linked(self):
        """1.2: the account is created on the guest record: My orders shows its order."""
        guest, order = self._guest('former.guest@example.com', name='Former Guest')
        self._sign_up('Former.Guest@example.com', name='Someone Else')
        self._verify()
        user = self.Users.search([('login', '=', 'former.guest@example.com')])
        self.assertEqual(user.partner_id, guest)
        self.assertEqual(user.name, 'Former Guest', "the record keeps its name")
        self.assertIn(order, self.env['sale.order'].with_user(user).search([]))
        self.assertEqual(self.env['res.partner'].search_count([('email_normalized', '=', 'former.guest@example.com'),
                                                               ('parent_id', '=', False)]), 1, "no second record")

    def test_several_guest_records(self):
        """4: the most recent record gets the account, the others are tagged for the daily check."""
        now = fields.Datetime.now()
        old, _old_order = self._guest('twice@example.com', name='Old', order_date=now - timedelta(days=30))
        new, _new_order = self._guest('twice@example.com', name='New', order_date=now - timedelta(days=1))
        self._sign_up('twice@example.com')
        self._verify()
        user = self.Users.search([('login', '=', 'twice@example.com')])
        self.assertEqual(user.partner_id, new)
        tag = self.env.ref('website_signup_verification.partner_tag_duplicate_email')
        self.assertIn(tag, old.category_id)
        self.assertNotIn(tag, new.category_id)
        self.assertIn('Merge', old.message_ids[0].body)

    def test_email_with_an_account(self):
        """1.3: no error, the sign-in message; no code is sent."""
        new_test_user(self.env, login='member@example.com', email='member@example.com', groups='base.group_portal')
        response = self._sign_up('member@example.com')
        self.assertIn('o_signup_account_exists', response.text)
        self.assertIn('You already have an account.', response.text)
        self.assertIn('reset your password', response.text)
        self.assertNotIn('Another user is already registered', response.text)
        self.assertNotIn('alert-danger', response.text)
        self.assertFalse(self.Verification.search([('email', '=', 'member@example.com')]))

    def test_code_expires_and_resend(self):
        """2.2: a short-lived code with a resend button."""
        self._sign_up('late@example.com')
        verification = self.Verification.search([('email', '=', 'late@example.com')])
        verification.code_expiry = fields.Datetime.now() - timedelta(seconds=1)
        self.assertIn('This code has expired', self._verify().text)

        page = self.url_open('/web/signup/verify').text
        self.assertIn('ask for a new code in', page, "not right away")
        verification.code_sent_at = fields.Datetime.now() - timedelta(minutes=2)
        with patch(RANDBELOW, return_value=111222):
            response = self.url_open('/web/signup/verify/resend', data={'csrf_token': self._csrf()})
        self.assertIn('We sent a new code', response.text)
        self.assertIn('This code is not right', self._verify(code=CODE).text, "the old code no longer works")
        self._verify(code=111222)
        self.assertTrue(self.Users.search([('login', '=', 'late@example.com')]))

    def test_too_many_tries(self):
        self._sign_up('guess@example.com')
        for _i in range(5):
            self._verify(code=999999)
        self.assertIn('Too many wrong codes', self._verify().text, "even the right code, until a new one")
        self.assertFalse(self.Users.search([('login', '=', 'guess@example.com')]))

    def test_switch_off(self):
        """The switch brings back the standard sign-up at once."""
        self.website.signup_verification = False
        self._sign_up('standard@example.com')
        user = self.Users.search([('login', '=', 'standard@example.com')])
        self.assertTrue(user, "created at once, without a code")
        self.assertFalse(user.signup_coupon_issued)


@tagged('post_install', '-at_install')
class TestSignupAfterOrder(SignupCommon):
    """Confirmation page "Create my account": the code goes to the order's email."""

    def test_confirmation_page(self):
        guest, order = self._guest('after.order@example.com', name='After Order')
        session = self.authenticate(None, None)
        session['sale_last_order_id'] = order.id
        root.session_store.save(session)
        with patch(RANDBELOW, return_value=CODE):
            response = self.url_open('/shop/order/signup', data={'csrf_token': self._csrf()})
        self.assertTrue(response.url.endswith('/web/signup/verify'))
        self.assertIn('Create my account', response.text)
        self.assertFalse(self.Users.search([('login', '=', 'after.order@example.com')]))

        response = self._verify(password='Another-pass1', confirm_password='nope')
        self.assertIn('Passwords do not match', response.text)
        response = self._verify(password='Another-pass1', confirm_password='Another-pass1')
        user = self.Users.search([('login', '=', 'after.order@example.com')])
        self.assertEqual(user.partner_id, guest)
        self.assertIn('/my/orders/%s' % order.id, response.url)
        self.authenticate('after.order@example.com', 'Another-pass1')


@tagged('post_install', '-at_install')
class TestSignupOauth(SignupCommon):
    """Annex 3A task 3: Google / Facebook, no code, the same matching."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['auth.oauth.provider'].create({
            'name': 'Test Google', 'client_id': 'x', 'auth_endpoint': 'https://example.com/auth',
            'validation_endpoint': 'https://example.com/userinfo', 'scope': 'email', 'body': 'Google',
        })

    def _signin(self, email, uid='g-1', verified=True):
        validation = {'user_id': uid, 'email': email, 'name': 'Google Name', 'email_verified': verified}
        params = {'access_token': 'token', 'state': json.dumps({'d': self.env.cr.dbname, 'p': self.provider.id})}
        return self.env['res.users'].sudo()._auth_oauth_signin(self.provider.id, validation, params)

    def test_guest_record_is_linked(self):
        guest, _order = self._guest('google.guest@example.com', name='Google Guest')
        login = self._signin('google.guest@example.com')
        user = self.Users.search([('login', '=', login)])
        self.assertEqual(user.partner_id, guest)
        self.assertEqual(user.oauth_uid, 'g-1')
        self.assertTrue(user.signup_coupon_issued)

    def test_new_email(self):
        login = self._signin('fresh.google@example.com')
        user = self.Users.search([('login', '=', login)])
        self.assertEqual(user.name, 'Google Name')
        self.assertTrue(user.signup_coupon_issued)

    def test_account_gets_the_provider(self):
        member = new_test_user(self.env, login='pw.member@example.com', email='pw.member@example.com',
                               groups='base.group_portal')
        self.assertEqual(self._signin('pw.member@example.com', uid='g-2'), member.login)
        self.assertEqual(member.oauth_uid, 'g-2')
        self.assertEqual(self._signin('pw.member@example.com', uid='g-2'), member.login, "next time: the usual sign-in")

    def test_unverified_email_is_not_linked(self):
        new_test_user(self.env, login='other.member@example.com', email='other.member@example.com',
                      groups='base.group_portal')
        with self.assertRaises(AccessDenied):
            self._signin('other.member@example.com', uid='g-3', verified=False)


@tagged('post_install', '-at_install')
class TestSignupEmail(SignupCommon):

    def test_code_email(self):
        """2.1: the code email, from no-reply@."""
        with self.mock_mail_gateway(), patch(RANDBELOW, return_value=42):
            self.Verification._start(self.website, 'mail.check@example.com', name='Mail Check')
        self.assertEqual(len(self._new_mails), 1)
        mail = self._new_mails
        self.assertIn('000042', mail.subject)
        self.assertIn('000042', mail.body_html)
        self.assertIn('no-reply@thecut.test', mail.email_from)
        sent = [email for email in self._mails if '000042' in email['subject']]
        self.assertEqual(len(sent), 1, "sent once")
        self.assertIn('mail.check@example.com', ' '.join(sent[0]['email_to']), "%s" % sent[0]['email_to'])
        self.assertIn('no-reply@thecut.test', sent[0]['email_from'])
