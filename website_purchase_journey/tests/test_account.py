from odoo.tests import new_test_user, tagged
from odoo.http import Request

from .test_order import OrderCommon


@tagged('post_install', '-at_install')
class TestAccount(OrderCommon):
    """My Account (Annex 3 B6, C7): lifetime savings, WhatsApp help, favourites."""

    def setUp(self):
        super().setUp()
        self.user = new_test_user(self.env, login='account', groups='base.group_portal')
        self.order = self._order(420, self.island, self.user.partner_id)
        self.order.action_confirm()
        self.authenticate('account', 'account')

    def test_lifetime_savings(self):
        saved = self.user.partner_id._journey_lifetime_savings(self.website)
        self.assertGreater(saved, 0, "free delivery above 400")
        self.assertEqual(saved, self.order._journey_summary(self.website)['savings'])
        self.assertIn('o_journey_lifetime_savings', self.url_open('/my').text)

        self._order(10, self.island, self.user.partner_id)
        self.assertEqual(self.user.partner_id._journey_lifetime_savings(self.website), saved, "carts do not count")

    def test_whatsapp_help(self):
        page = self.url_open('/my').text
        self.assertNotIn('o_journey_whatsapp', page, "no number: no button")
        self.assertNotIn('Your contact', page, "replaced")

        self.website.journey_whatsapp_number = '+971 50 717 9729'
        self.assertIn('https://wa.me/971507179729', self.url_open('/my').text)
        order_page = self.url_open('/my/orders/%s' % self.order.id).text
        self.assertIn('https://wa.me/971507179729?text=Hello%2C%20I%20need%20help%20with%20my%20order%20' + self.order.name, order_page)
        self.assertNotIn('portal_connect_software_modal_btn', order_page, "no 'Connect with your software'")
        self.assertIn('wa.me/971507179729', self.url_open('/my/orders/%s/track' % self.order.id).text)

    def test_favourites(self):
        self.assertIn('/shop/wishlist', self.url_open('/my').text)
        self.assertIn('o_journey_fav', self.url_open('/shop').text)
        self.assertIn('My favourites', self.url_open('/shop/wishlist').text)

    def test_switched_off(self):
        self.website.journey_enabled = False
        self.website.journey_whatsapp_number = '+971 50 717 9729'
        page = self.url_open('/my').text
        self.assertNotIn('o_journey_lifetime_savings', page)
        self.assertNotIn('o_journey_whatsapp', page)

    def test_account_phone_is_a_real_number(self):
        partner = self.user.partner_id
        form = {
            'partner_id': str(partner.id), 'name': partner.name, 'email': 'account@example.com',
            'street': 'Tower A', 'city': 'Abu Dhabi', 'zipcode': '00000', 'country_id': self.env.ref('base.ae').id,
            'state_id': self.env['res.country.state'].search([('country_id.code', '=', 'AE')], limit=1).id,
            'csrf_token': Request.csrf_token(self),
        }
        for wrong in ('12w3e4567', '+91 86062 91751'):
            result = self.url_open('/my/address/submit', data=dict(form, phone=wrong)).json()
            self.assertIn('phone', result['invalid_fields'], "%s is not a UAE number" % wrong)
            self.assertNotEqual(partner.phone, wrong)

        result = self.url_open('/my/address/submit', data=dict(form, phone='050 111 2233')).json()
        self.assertNotIn('invalid_fields', result)
        self.assertEqual(partner.phone, '+971 50 111 2233')

    def test_order_page(self):
        """Download invoice, no terms / payment terms / messages, no Track once delivered."""
        self.order.payment_term_id = self.env.ref('account.account_payment_term_immediate')
        page = self.url_open('/my/orders/%s' % self.order.id).text
        self.assertIn('o_journey_download_order', page, "not invoiced yet: the order PDF")
        self.assertNotIn('View Details', page)
        self.assertNotIn('sale_order_communication', page)
        self.assertNotIn('Payment terms', page)
        self.assertIn('o_journey_track_btn', page)
        self.assertIn('o_journey_conf_addresses', page, "the addresses in one small box")
        self.assertNotIn('id="customer_info"', page)

        invoice = self.order._create_invoices()
        invoice.action_post()
        page = self.url_open('/my/orders/%s' % self.order.id).text
        self.assertIn('o_journey_download_invoice', page)
        self.assertIn('/my/invoices/%s' % invoice.id, page)

        # Stage straight in the database (the delivery rules are tested in Online Orders)
        stage = self.env['online.order.stage']._get_by_code('delivered')
        self.env.cr.execute("UPDATE sale_order SET stage_id = %s WHERE id = %s", (stage.id, self.order.id))
        self.order.invalidate_recordset(['stage_id'])
        page = self.url_open('/my/orders/%s' % self.order.id).text
        self.assertNotIn('o_journey_track_btn', page, "delivered: nothing to track")

