import json

from odoo.tests import HttpCase, tagged

from odoo.addons.website_delivery_geolocation.controllers.portal import CustomerPortalDeliveryAddress
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website_sale.tests.common import MockRequest, WebsiteSaleCommon


@tagged('post_install', '-at_install')
class TestApartmentRequired(WebsiteSaleCommon):

    def setUp(self):
        super().setUp()
        # Same combination Odoo builds for the routes (all CustomerPortal extensions)
        self.controller = type('Controller', (CustomerPortalDeliveryAddress, WebsiteSale), {})()
        self.address_values = {
            'name': 'Receiver',
            'email': 'receiver@example.com',
            'phone': '+971500000000',
            'street': 'Tower A',
            'city': 'Abu Dhabi',
            'zip': '1200',
            'country_id': self.country_be.id,
            # Pin from the map: avoids geocoding during the test
            'partner_latitude': '24.4539',
            'partner_longitude': '54.3773',
            'address_type': 'delivery',
        }

    def _submit(self, **values):
        with MockRequest(self.env, website=self.website, sale_order_id=self.cart.id) as req:
            req.httprequest.method = 'POST'
            return json.loads(self.controller.shop_address_submit(**values).data)

    def test_delivery_address_without_apartment_is_refused(self):
        children = self.partner.child_ids
        feedback = self._submit(**self.address_values)
        self.assertIn('street2', feedback.get('invalid_fields', []))
        self.assertEqual(self.partner.child_ids, children, "no address should be created")

    def test_delivery_address_with_apartment_is_saved(self):
        feedback = self._submit(**self.address_values, street2='Apt 1203')
        self.assertFalse(feedback.get('invalid_fields'))
        address = self.cart.partner_shipping_id
        self.assertEqual(address.street2, 'Apt 1203')
        self.assertAlmostEqual(address.partner_latitude, 24.4539, places=4)

    def test_billing_does_not_require_apartment(self):
        with MockRequest(self.env, website=self.website, sale_order_id=self.cart.id):
            billing = self.controller._get_mandatory_billing_address_fields(self.country_be)
            delivery = self.controller._get_mandatory_delivery_address_fields(self.country_be)
        self.assertNotIn('street2', billing)
        self.assertIn('street2', delivery)


@tagged('post_install', '-at_install')
class TestApartmentRequiredRoute(HttpCase):
    """The address form reads the required fields from this route: street2
    must be marked required for delivery addresses (checkout and My Account)."""

    def _required_fields(self, address_type):
        country = self.env.ref('base.ae')
        result = self.make_jsonrpc_request(
            f'/my/address/country_info/{country.id}', {'address_type': address_type})
        return result['required_fields']

    def test_country_info_marks_apartment_required(self):
        self.assertIn('street2', self._required_fields('delivery'))
        self.assertNotIn('street2', self._required_fields('billing'))


@tagged('post_install', '-at_install')
class TestAddressCards(HttpCase):
    """My Account > Addresses shows the label, receiver mobile and driver directions."""

    def test_my_addresses(self):
        from odoo.tests import new_test_user
        user = new_test_user(self.env, login='addresses', groups='base.group_portal')
        self.env['res.partner'].create({
            'name': 'Receiver', 'parent_id': user.partner_id.id, 'type': 'delivery',
            'street': 'Tower A', 'street2': 'Apt 5', 'city': 'Abu Dhabi', 'country_id': self.env.ref('base.ae').id,
            'phone': '+971500000077', 'address_label': 'work', 'delivery_directions': 'Gate 3, then the lift',
            'partner_latitude': 24.45, 'partner_longitude': 54.37,
        })
        self.authenticate('addresses', 'addresses')
        page = self.url_open('/my/addresses').text
        self.assertIn('o_address_card_label', page)
        self.assertIn('Work', page)
        self.assertIn('Gate 3, then the lift', page)
        self.assertIn('+971500000077', page)

    def test_map_on_my_account_address(self):
        """Add / Edit of a delivery address in My Account shows the map; its pin is saved."""
        from odoo.http import Request
        from odoo.tests import new_test_user
        user = new_test_user(self.env, login='mapaddr', groups='base.group_portal')
        self.authenticate('mapaddr', 'mapaddr')
        self.assertIn('o_delivery_map', self.url_open('/my/address?address_type=delivery').text)
        self.assertNotIn('o_delivery_map', self.url_open('/my/address?address_type=billing').text)
        user.partner_id.write({'partner_latitude': 24.4501, 'partner_longitude': 54.3702})
        page = self.url_open('/my/account').text
        self.assertIn('o_delivery_map', page, "Account details (Edit): the main address has the map too")
        self.assertIn('o_geo_picker_only', page, "the map opens from the button only")
        self.assertIn('o_map_open_btn', page)
        self.assertIn('Change location on map', page, "a saved pin")
        self.assertNotIn('o_map_open_btn', self.url_open('/my/address?address_type=delivery').text,
                         "Addresses: the map is on the page")
        self.assertIn('data-init-lat="24.4501"', page)

        country = self.env.ref('base.ae')
        result = self.url_open('/my/address/submit', data={
            'address_type': 'delivery', 'name': 'Receiver', 'email': 'mapaddr@example.com',
            'phone': '+971500000078', 'street': 'Tower B', 'street2': 'Apt 9', 'city': 'Abu Dhabi',
            'zipcode': '00000', 'country_id': country.id,
            'state_id': self.env['res.country.state'].search([('country_id', '=', country.id)], limit=1).id,
            'partner_latitude': '24.4612', 'partner_longitude': '54.3801',
            'csrf_token': Request.csrf_token(self),
        }).json()
        self.assertFalse(result.get('invalid_fields'), result)
        address = user.partner_id.child_ids.filtered(lambda p: p.street == 'Tower B')
        self.assertAlmostEqual(address.partner_latitude, 24.4612, places=4)
        self.assertAlmostEqual(address.partner_longitude, 54.3801, places=4)
        page = self.url_open('/my/address?address_type=delivery&partner_id=%s' % address.id).text
        self.assertIn('data-init-lat="24.4612"', page, "editing starts at the saved pin")
