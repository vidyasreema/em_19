from odoo.tests import tagged

from odoo.addons.delivery_timeslot_module.controllers.main import DeliveryTimingController
from odoo.addons.website_sale.tests.common import MockRequest, WebsiteSaleCommon


@tagged('post_install', '-at_install')
class TestSaveDeliveryTiming(WebsiteSaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['store.settings'].get_store_settings(cls.website.id)
        # The cart of the user of the (mocked) request, like a real customer's cart:
        # otherwise the request moves the cart to that user, and the zone check of
        # website_delivery_geolocation clears its delivery method.
        cls.cart.partner_id = cls.env.user.partner_id

    def _save(self, order=None):
        order_id = order.id if order else None
        with MockRequest(self.env, website=self.website, sale_order_id=order_id):
            return DeliveryTimingController().save_delivery_timing()

    def test_delivery_promise_saved_on_cart(self):
        self.cart.carrier_id = self.carrier
        result = self._save(order=self.cart)
        self.assertTrue(result['success'], result.get('error'))
        self.assertTrue(self.cart.delivery_promise_until)
        self.assertEqual(self.cart.commitment_date, self.cart.delivery_promise_until)

    def test_dates_sent_by_the_page_are_ignored(self):
        self.cart.carrier_id = self.carrier
        with MockRequest(self.env, website=self.website, sale_order_id=self.cart.id):
            DeliveryTimingController().save_delivery_timing(
                delivery_data={'delivery_date': 'Monday, January 01, 2024'})
        self.assertNotEqual(self.cart.commitment_date.year, 2024)

    def test_cart_without_delivery_method(self):
        result = self._save(order=self.cart)
        self.assertFalse(result['success'])

    def test_timing_as_website_visitor(self):
        """Guests can't read the company contact: the timing must still be
        computed (the banner, popup and saved date all depend on it)."""
        website = self.website.with_user(self.public_user)
        with MockRequest(website.env, website=website):
            result = DeliveryTimingController().get_delivery_timing(carrier_id=self.carrier.id)
        self.assertIn(result['scenario'], (1, 2, 3))
        self.assertTrue(result['delivery_date'])

    def test_timing_uses_cart_delivery_method(self):
        """The payment page sends no delivery method: the cart's one is used."""
        self.cart.carrier_id = self.carrier
        with MockRequest(self.env, website=self.website, sale_order_id=self.cart.id):
            result = DeliveryTimingController().get_delivery_timing()
        self.assertTrue(result['delivery_date'])

    def test_no_cart(self):
        """A guest without a cart."""
        website = self.website.with_user(self.public_user)
        with MockRequest(website.env, website=website):
            result = DeliveryTimingController().save_delivery_timing()
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'No active order found')
