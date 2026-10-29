import base64
from email.utils import formataddr

from odoo import Command
from odoo.tools import email_normalize
from odoo.tests import new_test_user, tagged

from odoo.addons.mail.tests.common import MockEmail
from odoo.addons.online_orders.tests.common import OnlineOrdersCommon

BRAND_MARK = 'border-top: 4px solid #7A1F2B'
PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
SVG = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>')


@tagged('post_install', '-at_install')
class TestBrandEmails(OnlineOrdersCommon, MockEmail):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website.write({'brand_emails': True, 'online_orders_email_from': 'orders@thecutuae.com'})
        cls.website.company_id.alias_domain_id = cls.env['mail.alias.domain'].create({'name': 'thecutuae.com'})
        cls.orders_from = formataddr((cls.website.name, 'orders@thecutuae.com'))
        cls.noreply_from = formataddr((cls.website.name, 'no-reply@thecutuae.com'))
        cls.portal_user = new_test_user(
            cls.env, login='brand_customer', groups='base.group_portal', email='brand.customer@example.com')

    def _mails_with(self, subject):
        return self._new_mails.filtered(lambda m: subject in (m.subject or ''))

    def _assert_brand(self, mail):
        self.assertIn(BRAND_MARK, mail.body_html, "The Cut layout")
        self.assertNotIn('Powered by', mail.body_html)

    def test_order_confirmation(self):
        order = self._create_order()
        with self.mock_mail_gateway():
            order._send_order_notification_mail(order._get_confirmation_template())
        mail = self._mails_with('is confirmed')
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.email_from, self.orders_from)
        self.assertIn('Thank you for your order', mail.body_html)
        self.assertIn('Ribeye', mail.body_html, "the order lines")
        self._assert_brand(mail)

    def test_wholesale_order_keeps_standard_email(self):
        order = self._create_order(website_id=False)
        with self.mock_mail_gateway():
            order._send_order_notification_mail(order._get_confirmation_template())
        self.assertFalse(self._mails_with('is confirmed'))
        self.assertNotIn(BRAND_MARK, self._new_mails[:1].body_html or '')

    def test_switch_off(self):
        self.website.brand_emails = False
        order = self._create_order()
        with self.mock_mail_gateway():
            order._send_order_notification_mail(order._get_confirmation_template())
        self.assertFalse(self._mails_with('is confirmed'), "the standard confirmation")

    def test_board_emails(self):
        order = self._tracked(self._create_order())
        with self.mock_mail_gateway():
            order.action_online_next_stage()
            self._flush_tracking()
        mail = self._mails_with('is on the way')
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.email_from, self.orders_from)
        self.assertIn('Track my order', mail.body_html)
        self._assert_brand(mail)

    def test_reset_password(self):
        with self.mock_mail_gateway():
            self.portal_user.action_reset_password()
        sent = [m for m in self._mails if 'Reset your' in m['subject']]
        self.assertEqual(len(sent), 1)
        self.assertEqual(email_normalize(sent[0]['email_from']), 'no-reply@thecutuae.com')
        self.assertIn('Choose a new password', sent[0]['body'])
        self.assertIn(BRAND_MARK, sent[0]['body'])
        self.assertNotIn('Public user', sent[0]['body'])

    def test_reset_password_of_employee_keeps_standard_email(self):
        employee = new_test_user(self.env, login='brand_employee', groups='base.group_user', email='employee@example.com')
        with self.mock_mail_gateway():
            employee.action_reset_password()
        self.assertFalse([m for m in self._mails if 'Reset your' in m['subject']])

    def test_account_emails(self):
        with self.mock_mail_gateway():
            self.env.ref('auth_signup.mail_template_user_signup_account_created').send_mail(self.portal_user.id)
            self.env.ref('auth_signup.portal_set_password_email').send_mail(self.portal_user.id)
        welcome = self._mails_with('Welcome to %s' % self.website.name)
        ready = self._mails_with('account is ready')
        self.assertEqual(len(welcome), 1)
        self.assertEqual(len(ready), 1)
        self.assertEqual(welcome.email_from, self.noreply_from)
        self.assertIn('Choose my password', ready.body_html)
        self._assert_brand(welcome)

    def test_coupon_email(self):
        program = self.env['loyalty.program'].create({
            'name': 'Brand coupons', 'program_type': 'coupons', 'ecommerce_ok': True,
            'reward_ids': [Command.create({'reward_type': 'discount', 'discount': 10, 'description': '10% off'})],
        })
        card = self.env['loyalty.card'].with_context(loyalty_no_mail=True).create({
            'program_id': program.id, 'partner_id': self.customer.id, 'points': 1})
        with self.mock_mail_gateway():
            self.env.ref('loyalty.mail_template_loyalty_card').send_mail(card.id)
        mail = self._mails_with('You have a coupon')
        self.assertEqual(len(mail), 1)
        self.assertIn(card.code, mail.body_html)
        self.assertEqual(mail.email_from, self.orders_from)
        self._assert_brand(mail)

    def _confirmation_body(self):
        order = self._create_order()
        with self.mock_mail_gateway():
            order._send_order_notification_mail(order._get_confirmation_template())
        return self._mails_with('is confirmed').body_html

    def test_svg_logo_is_not_used(self):
        """Gmail and Outlook do not show SVG images: the name of the website instead."""
        self.website.write({'logo': SVG, 'brand_email_logo': False})
        body = self._confirmation_body()
        self.assertNotIn('/web/image/website/%s/logo' % self.website.id, body)
        self.assertIn(self.website.name, body)

    def test_email_logo(self):
        self.website.write({'logo': SVG, 'brand_email_logo': PNG})
        body = self._confirmation_body()
        self.assertIn('/web/image/website/%s/brand_email_logo' % self.website.id, body)
