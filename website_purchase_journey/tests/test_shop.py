from odoo.tests import tagged

from odoo.addons.website_sale.tests.common import MockRequest

from .common import JourneyCommon


@tagged('post_install', '-at_install')
class TestJourneyShop(JourneyCommon):
    """Annex 3: C1 (add button), v2 §6 (weight choice)."""

    def _tile(self, template):
        with MockRequest(self.env, website=self.website):
            return template._journey_tile_info(self.website)

    def test_multi_weight_card(self):
        info = self._tile(self.multi)
        self.assertTrue(info['multi'], "several weights: Choose weight")
        self.assertEqual(info['from_price'], 35.0, "from the cheapest weight")
        self.assertTrue(info['show_from'])
        self.assertFalse(info['out_of_stock'])

    def test_single_and_sold_out_cards(self):
        self.assertFalse(self._tile(self.single)['multi'], "one weight: direct Add")
        self.assertFalse(self._tile(self.single)['out_of_stock'])
        self.assertTrue(self._tile(self.sold_out)['out_of_stock'], "disabled by the ribbon")

    def test_other_ribbon_keeps_add(self):
        self.single.website_ribbon_id = self.sale_ribbon
        self.assertFalse(self._tile(self.single)['out_of_stock'], "only the out of stock ribbons disable")

    def test_availability_ignores_quantity(self):
        self.single.is_storable = True  # no stock at all
        self.assertFalse(self._tile(self.single)['out_of_stock'], "the ribbon is the single source")

    def test_weight_rows(self):
        self.variant_250.variant_ribbon_id = self.out_of_stock
        with MockRequest(self.env, website=self.website):
            rows = self.multi._journey_weight_rows(self.website)
        self.assertEqual([r['label'] for r in rows], ['250 g', '500 g', '1 kg'], "cheapest first")
        self.assertEqual([r['price'] for r in rows], [35.0, 60.0, 100.0], "prices read from the variants")
        self.assertEqual([r['out_of_stock'] for r in rows], [True, False, False], "a variant can be out of stock")

    def test_shop_page(self):
        page = self.url_open('/shop').text
        self.assertIn('o_journey_choose', page)
        self.assertIn('o_journey_add', page)
        self.assertIn('o_journey_out_of_stock', page)
        self.assertIn('o_journey_from', page)
        self.assertIn('Same-day delivery in Abu Dhabi for orders before 7:00 PM', page, "general message")

    def test_switch_off(self):
        self.website.journey_enabled = False
        page = self.url_open('/shop').text
        self.assertNotIn('o_journey_tile_actions', page)
        self.assertNotIn('o_journey_location_bar', page)
        self.assertIn('TOUR Ribeye', page)

    def test_view_cart_button(self):
        self.authenticate(None, None)
        self.assertRegex(self.url_open('/shop').text, r'o_journey_cart_bar d-none', "empty cart: hidden")
        self.assertEqual(self.make_jsonrpc_request('/shop/journey/cart_total', {})['quantity'], 0)

        variant = self.single.product_variant_id
        self.make_jsonrpc_request('/shop/cart/add', {
            'product_template_id': self.single.id, 'product_id': variant.id, 'quantity': 2})
        total = self.make_jsonrpc_request('/shop/journey/cart_total', {})
        self.assertEqual(total['quantity'], 2)
        self.assertTrue(total['amount'])
        page = self.url_open('/shop').text
        self.assertRegex(page, r'o_journey_cart_bar "', "shown")
        self.assertIn('View cart', page)
        self.assertNotIn('o_journey_cart_bar', self.url_open('/shop/order').text, "not on the order page")

    def test_weights_route(self):
        result = self.make_jsonrpc_request('/shop/journey/weights', {'product_template_id': self.multi.id})
        self.assertIn('250 g', result['html'])
        self.assertIn('o_journey_sheet_add', result['html'])
        self.multi.is_published = False
        result = self.make_jsonrpc_request('/shop/journey/weights', {'product_template_id': self.multi.id})
        self.assertEqual(result['html'], '', "an unpublished product is not shown")


@tagged('post_install', '-at_install')
class TestJourneyLocation(JourneyCommon):
    """Annex 3: C2 (location on entry), D3 (promise in the bar)."""

    def _set(self, lat, lng, area=''):
        return self.make_jsonrpc_request('/shop/journey/set_location', {'latitude': lat, 'longitude': lng, 'area': area})

    def test_location_in_zone(self):
        result = self._set(24.4539, 54.3773, 'Al Reem Island')
        self.assertTrue(result['zone_found'])
        self.assertIn('Al Reem Island', result['bar_html'])
        self.assertIn('Delivered today within 3 hours', result['bar_html'], "the promise of the zone")
        page = self.url_open('/shop').text
        self.assertIn('Al Reem Island', page, "kept for the visit")

    def test_location_without_area_name(self):
        result = self._set(24.4539, 54.3773)
        self.assertIn('Abu Dhabi Island', result['bar_html'], "the zone name when the area is unknown")

    def test_location_outside_zones(self):
        result = self._set(25.2048, 55.2708)
        self.assertFalse(result['zone_found'])
        self.assertIn("deliver to this location yet", result['bar_html'])

    def test_invalid_location(self):
        with self.assertRaises(Exception):
            self._set('north', 'east')

    def test_location_starts_the_first_address(self):
        with MockRequest(self.env, website=self.website) as request:
            request.session['journey_latitude'] = 24.4539
            request.session['journey_longitude'] = 54.3773
            self.assertEqual(self.website._geo_address_initial_point(self.env['res.partner']), (24.4539, 54.3773))
            address = self.env['res.partner'].create({'name': 'Home', 'street': 'Tower A'})
            self.assertIsNone(self.website._geo_address_initial_point(address), "a filled address is not moved")

    def test_no_bar_during_checkout(self):
        with MockRequest(self.env, website=self.website, path='/shop/payment'):
            self.assertFalse(self.website._journey_show_location_bar())
        with MockRequest(self.env, website=self.website, path='/shop'):
            self.assertTrue(self.website._journey_show_location_bar())
