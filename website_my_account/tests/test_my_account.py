from odoo import Command
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestMyAccount(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].get_current_website()
        cls.website.write({'my_account_page': True, 'journey_enabled': True})
        cls.user = new_test_user(cls.env, login='my.account@example.com', email='my.account@example.com',
                                 name='Hala Test', groups='base.group_portal')
        cls.product = cls.env['product.product'].create({'name': 'Ribeye', 'list_price': 50})

    def _page(self):
        self.authenticate(self.user.login, self.user.login)
        response = self.url_open('/my')
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_page(self):
        page = self._page()
        self.assertIn('o_my_account', page)
        self.assertIn('Hala Test', page)
        self.assertIn('My Orders', page)
        for url in ('/my/addresses', '/my/payment_method', '/shop/wishlist', '/my/security', '/web/session/logout'):
            self.assertIn(url, page)
        self.assertNotIn('/my/invoices', page, "no invoices: no row")

    def test_profile_completion(self):
        page = self._page()
        self.assertIn('50%', page, "name and email of 4 steps")
        self.assertIn('your mobile number and a delivery address', page)
        self.user.partner_id.write({'phone': '+971 50 111 2233', 'street': 'Tower A'})
        page = self._page()
        self.assertNotIn('o_my_progress', page, "complete: no bar")

    def test_last_order(self):
        order = self.env['sale.order'].create({
            'partner_id': self.user.partner_id.id,
            'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.product.id})],
        })
        order.action_confirm()
        self.assertIn(order.name, self._page())

    def test_switch_off(self):
        self.website.my_account_page = False
        page = self._page()
        self.assertNotIn('o_my_account', page)
        self.assertIn('o_portal_my_home', page, "the standard page")

    def test_account_details_without_business_fields(self):
        self.authenticate(self.user.login, self.user.login)
        page = self.url_open('/my/account').text
        for name in ('name="company_name"', 'name="vat"', 'name="invoice_sending_method"', 'name="invoice_edi_format"'):
            self.assertNotIn(name, page)
        self.assertIn('name="phone"', page)

        self.website.my_account_page = False
        self.assertIn('name="company_name"', self.url_open('/my/account').text, "switch off: the standard page")

    def test_address_form_without_business_fields(self):
        self.authenticate(self.user.login, self.user.login)
        for url in ('/my/address?partner_id=%s' % self.user.partner_id.id, '/my/address'):
            page = self.url_open(url).text
            self.assertIn('name="street"', page, url)
            self.assertNotIn('name="company_name"', page, url)
            self.assertNotIn('name="vat"', page, url)

        self.website.my_account_page = False
        page = self.url_open('/my/address?partner_id=%s' % self.user.partner_id.id).text
        self.assertIn('name="company_name"', page, "switch off: the standard form")
