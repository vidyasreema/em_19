import json

from odoo import Command, http
from odoo.tests import new_test_user, tagged

from odoo.addons.website_sale.tests.common import MockRequest

from .common import JourneyCommon


class OrderCommon(JourneyCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Island: free delivery above 400. Dubai: free above 800.
        cls.island.write({'free_over': True, 'amount': 400.0, 'website_published': True})
        product = cls.env['product.product'].create({'name': 'Delivery Dubai', 'type': 'service'})
        cls.dubai = cls.env['delivery.carrier'].create({
            'name': 'Other Emirates', 'product_id': product.id, 'delivery_type': 'fixed', 'fixed_price': 55.0,
            'free_over': True, 'amount': 800.0, 'website_published': True,
            'message_scenario_1': '', 'message_scenario_2': 'Delivered {day} afternoon',
        })
        dubai_square = {'inclusion': {'type': 'Polygon', 'coordinates': [[
            [55.10, 25.10], [55.40, 25.10], [55.40, 25.30], [55.10, 25.30], [55.10, 25.10]]]}, 'exclusions': []}
        cls.env['delivery.zone'].create({
            'name': 'Dubai', 'polygon': json.dumps(dubai_square), 'delivery_method_id': cls.dubai.id})
        cls.env['delivery.carrier'].search([('id', 'not in', (cls.island | cls.dubai).ids)]).active = False

        # One unit = 1.00, no tax: easy amounts (399, 405...)
        cls.unit = cls.env['product.product'].create({
            'name': 'TOUR Mince (unit)', 'list_price': 1.0, 'type': 'consu', 'is_published': True,
            'sale_ok': True, 'taxes_id': [Command.clear()],
        })
        cls.promo = cls.env['loyalty.program'].create({
            'name': 'Test 10', 'program_type': 'promo_code', 'trigger': 'with_code',
            'rule_ids': [Command.create({'code': 'TEST10', 'minimum_amount': 0})],
            'reward_ids': [Command.create({
                'reward_type': 'discount', 'discount': 10, 'discount_mode': 'percent',
                'discount_applicability': 'order', 'description': '10% off'})],
        })
        cls.welcome = cls.env.ref('website_purchase_journey.loyalty_program_welcome_signup')
        cls.website.journey_welcome_program_id = cls.welcome

    def _address(self, lat, lng, parent=None, **values):
        return self.env['res.partner'].create({
            'name': values.pop('name', 'Receiver'), 'parent_id': parent and parent.id, 'type': 'delivery' if parent else 'contact',
            'street': 'Tower A', 'street2': 'Apt 5', 'city': 'Abu Dhabi', 'country_id': self.env.ref('base.ae').id,
            'phone': '+971500000009', 'email': 'receiver@example.com',
            'partner_latitude': lat, 'partner_longitude': lng, **values,
        })

    def _order(self, amount, carrier, partner=None):
        partner = partner or self._address(24.4539, 54.3773)
        order = self.env['sale.order'].create({
            'partner_id': partner.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.unit.id, 'product_uom_qty': amount})],
        })
        order._set_delivery_method(carrier, rate=carrier.rate_shipment(order))
        return order

    def _apply(self, order, code='TEST10'):
        status = order._try_apply_code(code)
        coupon, rewards = next(iter(status.items()))
        order._apply_program_reward(rewards, coupon)
        return -sum(order.order_line.filtered(lambda l: l.reward_id.reward_type == 'discount').mapped('price_total'))


@tagged('post_install', '-at_install')
class TestCouponBase(OrderCommon):
    """Annex 3 §9 and check 3 of §10."""

    def test_below_threshold_full_amount(self):
        order = self._order(399, self.island)
        self.assertAlmostEqual(self._apply(order), 39.9)
        self.assertEqual(order.amount_delivery, 40.0, "fee 40 below 400")
        self.assertIn('applied on the full amount', order._journey_coupon_message(self.promo.reward_ids))
        self.assertIn('399.00', order._journey_coupon_message(self.promo.reward_ids))

    def test_above_threshold_only_the_part_above(self):
        order = self._order(405, self.island)
        self.assertAlmostEqual(self._apply(order), 0.5, msg="10% of the 5 above 400")
        self.assertEqual(order.amount_delivery, 0.0, "free delivery")
        message = order._journey_coupon_message(self.promo.reward_ids)
        self.assertRegex(message, r'applied on \S+\s?5\.00, the amount above \S+\s?400\.00, because delivery is now free')

    def test_dubai_threshold_800(self):
        order = self._order(405, self.dubai, partner=self._address(25.2, 55.27))
        self.assertAlmostEqual(self._apply(order), 40.5, msg="below 800: full amount")
        self.assertEqual(order.amount_delivery, 55.0)
        order = self._order(900, self.dubai, partner=self._address(25.2, 55.27))
        self.assertAlmostEqual(self._apply(order), 10.0, msg="10% of the 100 above 800")

    def test_switch_off_keeps_standard_coupon(self):
        self.website.journey_enabled = False
        order = self._order(405, self.island)
        self.assertAlmostEqual(self._apply(order), 40.5)

    def test_signup_saving(self):
        """Version 2 check: carts of 380 and 450 show 38 and 5."""
        self.assertAlmostEqual(self._order(380, self.island)._journey_signup_saving(self.website), 38.0)
        self.assertAlmostEqual(self._order(450, self.island)._journey_signup_saving(self.website), 5.0)

    def test_summary_free_delivery_and_savings(self):
        order = self._order(405, self.island)
        self._apply(order)
        summary = order._journey_summary(self.website)
        self.assertTrue(summary['free_delivery'])
        self.assertEqual(summary['delivery_base_fee'], 40.0, "the value of free delivery")
        self.assertAlmostEqual(summary['savings'], 40.5, msg="coupon 0.50 + free delivery 40")
        self.assertEqual(summary['items_count'], 405)
        summary = self._order(380, self.island)._journey_summary(self.website)
        self.assertEqual(summary['left_for_free'], 20.0)
        self.assertEqual(summary['progress'], 95)


@tagged('post_install', '-at_install')
class TestWelcomeCoupon(OrderCommon):
    """Version 2 §4.2: the welcome coupon comes with the account."""

    def test_signup_gives_welcome_coupon(self):
        self.env['ir.config_parameter'].sudo().set_param('auth_signup.invitation_scope', 'b2c')
        self.env['res.users'].sudo().signup({'login': 'new.member@example.com', 'name': 'New Member', 'password': 'Member1234'})
        user = self.env['res.users'].search([('login', '=', 'new.member@example.com')])
        card = self.env['loyalty.card'].search([('program_id', '=', self.welcome.id), ('partner_id', '=', user.partner_id.id)])
        self.assertEqual(len(card), 1)
        self.assertGreater(card.points, 0)

    def test_archived_program_gives_nothing(self):
        self.welcome.active = False
        self.env['ir.config_parameter'].sudo().set_param('auth_signup.invitation_scope', 'b2c')
        self.env['res.users'].sudo().signup({'login': 'late.member@example.com', 'name': 'Late', 'password': 'Member1234'})
        user = self.env['res.users'].search([('login', '=', 'late.member@example.com')])
        self.assertFalse(self.env['loyalty.card'].with_context(active_test=False).search([('partner_id', '=', user.partner_id.id)]))
        self.assertEqual(self._order(380, self.island)._journey_signup_saving(self.website), 0.0, "no 'Sign up and save'")

    def test_one_coupon_per_customer(self):
        partner = self.env['res.partner'].create({'name': 'Once'})
        self.welcome._journey_give_welcome_coupon(partner)
        self.welcome._journey_give_welcome_coupon(partner)
        self.assertEqual(self.env['loyalty.card'].search_count([('program_id', '=', self.welcome.id), ('partner_id', '=', partner.id)]), 1)


@tagged('post_install', '-at_install')
class TestOrderPage(OrderCommon):

    def _guest_cart(self, quantity=1):
        self.make_jsonrpc_request('/shop/cart/add', {
            'product_template_id': self.unit.product_tmpl_id.id, 'product_id': self.unit.id, 'quantity': quantity})
        return self.env['sale.order'].search([('website_id', '=', self.website.id)], order='id desc', limit=1)

    def _give_address(self, order, lat=24.4539, lng=54.3773):
        guest = self._address(lat, lng, name='Guest Buyer')
        order.write({'partner_id': guest.id, 'partner_shipping_id': guest.id, 'partner_invoice_id': guest.id})
        return guest

    def test_steps_lead_to_the_order_page(self):
        self._guest_cart()
        for path in ('/shop/cart', '/shop/checkout', '/shop/payment'):
            response = self.url_open(path, allow_redirects=False)
            self.assertIn(response.status_code, (302, 303), path)
            self.assertTrue(response.headers['Location'].endswith('/shop/order'), path)

    def test_switch_off_keeps_standard_steps(self):
        self.website.journey_enabled = False
        self._guest_cart()
        response = self.url_open('/shop/order', allow_redirects=False)
        self.assertTrue(response.headers['Location'].endswith('/shop/cart'))

    def test_empty_cart(self):
        page = self.url_open('/shop/order').text
        self.assertIn('Your cart is empty.', page)

    def test_guest_page(self):
        self._guest_cart(380)
        page = self.url_open('/shop/order').text
        self.assertIn('New here? Sign up and get 10% off', page)
        self.assertIn('Continue as guest', page)
        self.assertIn('Email (required, for your order confirmation)', page)
        self.assertIn('Email me with news and offers', page)
        self.assertIn('Add delivery address', page)
        self.assertIn('Add your address', page, "no delivery fee before the address")

    def test_guest_with_address(self):
        order = self._guest_cart(380)
        self._give_address(order)
        page = self.url_open('/shop/order').text
        self.assertEqual(order.carrier_id, self.island, "delivery method of the zone")
        self.assertIn('Delivered today within 3 hours', page, "the promise")
        self.assertRegex(page, r'o_journey_promise_date">\w{3} \d{1,2} \w{3} · by ', "with its date and time")
        self.assertIn('Sign up and save', page)
        self.assertIn('38.00', page, "10% of 380")
        self.assertIn('to get <b>free delivery</b>', page)
        self.assertIn('Received by', page)

    def test_free_delivery_page(self):
        order = self._guest_cart(405)
        self._give_address(order)
        page = self.url_open('/shop/order').text
        self.assertIn('Free delivery unlocked.', page)
        self.assertIn('Your savings on this order', page)
        self.assertEqual(order.amount_delivery, 0.0)

    def test_prepare_checks_the_form(self):
        order = self._guest_cart(10)
        result = self.make_jsonrpc_request('/shop/order/prepare', {'email': 'x@example.com'})
        self.assertEqual(result['field'], 'address')
        guest = self._give_address(order)
        result = self.make_jsonrpc_request('/shop/order/prepare', {'email': 'not-an-email'})
        self.assertEqual(result['field'], 'email', "the email is required for guests")
        result = self.make_jsonrpc_request('/shop/order/prepare', {
            'email': 'buyer@example.com', 'consent': True, 'call_on_arrival': True,
            'note': 'Gate 2, then the lift', 'save_note': True,
        })
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(guest.email, 'buyer@example.com')
        self.assertTrue(guest.marketing_consent, "explicit consent saved on the customer")
        self.assertTrue(guest.marketing_consent_date)
        self.assertTrue(order.delivery_call_on_arrival)
        self.assertEqual(order.order_note, 'Gate 2, then the lift')
        self.assertEqual(guest.delivery_directions, 'Gate 2, then the lift', "saved for this address")

    def test_consent_unticked_by_default(self):
        order = self._guest_cart(10)
        guest = self._give_address(order)
        self.make_jsonrpc_request('/shop/order/prepare', {'email': 'buyer@example.com'})
        self.assertFalse(guest.marketing_consent)

    def test_coupon_routes(self):
        order = self._guest_cart(405)
        self._give_address(order)
        self.url_open('/shop/order')
        result = self.make_jsonrpc_request('/shop/order/coupon', {'code': 'NOPE'})
        self.assertFalse(result['ok'])
        page = self.url_open('/shop/order').text
        self.assertIn('Check the spelling', page, "the error is shown once after the reload")
        self.assertNotIn('Check the spelling', self.url_open('/shop/order').text)
        result = self.make_jsonrpc_request('/shop/order/coupon', {'code': 'TEST10'})
        self.assertTrue(result['ok'], result)
        page = self.url_open('/shop/order').text
        self.assertRegex(page, r'the amount above [^,]*400\.00, because delivery is now free')
        line = order.order_line.filtered(lambda l: l.reward_id == self.promo.reward_ids)
        self.make_jsonrpc_request('/shop/order/coupon/remove', {'line_id': line.id})
        self.assertFalse(order.order_line.filtered(lambda l: l.reward_id == self.promo.reward_ids))

    def test_member_gets_welcome_coupon_applied(self):
        user = new_test_user(self.env, login='member', groups='base.group_portal', email='member@example.com')
        address = self._address(24.4539, 54.3773, parent=user.partner_id, name='Home')
        user.partner_id.write({'street': 'Villa 1', 'city': 'Abu Dhabi', 'country_id': self.env.ref('base.ae').id,
                               'partner_latitude': 24.4539, 'partner_longitude': 54.3773, 'phone': '+971500000001'})
        self.welcome._journey_give_welcome_coupon(user.partner_id)
        order = self.env['sale.order'].create({
            'partner_id': user.partner_id.id, 'partner_shipping_id': address.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.unit.id, 'product_uom_qty': 380})],
        })
        self.authenticate('member', 'member')
        page = self.url_open('/shop/order').text
        self.assertIn('Signed in as', page)
        self.assertNotIn('New here? Sign up', page)
        self.assertTrue(order.order_line.filtered(lambda l: l.reward_id.program_id == self.welcome),
                        "the welcome coupon is applied after signing up")
        self.assertIn('applied on the full amount', page)

    def _member_cart(self, login):
        user = new_test_user(self.env, login=login, groups='base.group_portal', email='%s@example.com' % login)
        user.partner_id.write({'street': 'Villa 1', 'city': 'Abu Dhabi', 'country_id': self.env.ref('base.ae').id,
                               'partner_latitude': 24.4539, 'partner_longitude': 54.3773, 'phone': '+971500000001'})
        order = self._order(10, self.island, user.partner_id)
        self.authenticate(login, login)
        return user, order

    def test_my_coupons_popup(self):
        user, order = self._member_cart('popupbuyer')
        card = self.env['loyalty.card'].create({
            'program_id': self.promo.id, 'partner_id': user.partner_id.id, 'points': 1})
        self.promo.program_type = 'coupons'
        page = self.url_open('/shop/order').text
        self.assertIn('o_journey_mycoupons_modal', page, "the popup is on the order page")
        self.assertIn('View my coupons (1)', page)
        self.assertIn(card.code, page, "with the code to copy")
        self.assertIn('o_journey_mycoupon_apply', page, "and Apply")
        self.assertNotIn('href="/my/coupons" class="small d-inline-block', page, "no link away from the page")

    def test_news_and_offers_for_new_customers(self):
        user, _order = self._member_cart('newbuyer')
        page = self.url_open('/shop/order').text
        self.assertIn('o_journey_consent', page, "first order: asked")
        self.make_jsonrpc_request('/shop/order/prepare', {'consent': True})
        self.assertTrue(user.partner_id.marketing_consent)

    def test_news_and_offers_not_asked_again(self):
        user, _order = self._member_cart('regular')
        user.partner_id._journey_set_marketing_consent(True)
        self._order(10, self.island, user.partner_id).action_confirm()
        page = self.url_open('/shop/order').text
        self.assertIn('Signed in as', page)
        self.assertNotIn('o_journey_consent', page, "returning customer: not asked")
        self.assertTrue(self.make_jsonrpc_request('/shop/order/prepare', {}).get('ok'))
        self.assertTrue(user.partner_id.marketing_consent, "their choice stays")


@tagged('post_install', '-at_install')
class TestMyCoupons(OrderCommon):
    """Annex 3 C5: list with code, minimum and expiry, and Apply to my order."""

    def setUp(self):
        super().setUp()
        self.user = new_test_user(self.env, login='couponer', groups='base.group_portal', email='couponer@example.com')
        self.user.partner_id.write({'street': 'Tower A', 'street2': 'Apt 5', 'city': 'Abu Dhabi',
                                    'country_id': self.env.ref('base.ae').id, 'phone': '+971500000002',
                                    'partner_latitude': 24.4539, 'partner_longitude': 54.3773})
        self.card = self.welcome._journey_give_welcome_coupon(self.user.partner_id)

    def test_page_lists_the_coupon(self):
        self.authenticate('couponer', 'couponer')
        page = self.url_open('/my/coupons').text
        self.assertIn(self.card.code, page)
        self.assertIn('10% off', page)
        self.assertIn('Members only · one use · no minimum', page)
        self.assertIn('Add products to your cart to use it.', page, "no cart: nothing to apply to")
        self.assertIn('My coupons', self.url_open('/my').text, "card on My Account")

    def test_apply_to_my_order(self):
        order = self.env['sale.order'].create({
            'partner_id': self.user.partner_id.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.unit.id, 'product_uom_qty': 100})],
        })
        self.authenticate('couponer', 'couponer')
        page = self.url_open('/my/coupons').text
        self.assertIn('Apply to my order', page)
        response = self.url_open('/my/coupons/apply', data={'card_id': self.card.id, 'csrf_token': http.Request.csrf_token(self)},
                                 allow_redirects=False)
        self.assertTrue(response.headers['Location'].endswith('/shop/order'))
        self.assertIn(self.card, order.applied_coupon_ids)
        self.assertIn('Applied to your order', self.url_open('/my/coupons').text)

    def test_used_and_expired(self):
        self.card.points = 0
        expired = self.welcome._journey_give_welcome_coupon(self.env['res.partner'].create({'name': 'Other'}))
        expired.write({'partner_id': self.user.partner_id.id, 'expiration_date': '2020-01-01'})
        current, past = self.env['loyalty.card']._journey_portal_coupons(self.user.partner_id)
        self.assertFalse(current)
        self.assertEqual(sorted(c['status'] for c in past), ['Expired', 'Used'])

    def test_cannot_apply_someone_elses_coupon(self):
        other = self.welcome._journey_give_welcome_coupon(self.env['res.partner'].create({'name': 'Other'}))
        order = self.env['sale.order'].create({
            'partner_id': self.user.partner_id.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.unit.id, 'product_uom_qty': 100})],
        })
        self.authenticate('couponer', 'couponer')
        self.url_open('/my/coupons/apply', data={'card_id': other.id, 'csrf_token': http.Request.csrf_token(self)})
        self.assertNotIn(other, order.applied_coupon_ids)

    def test_new_coupon_party(self):
        other = self.welcome._journey_give_welcome_coupon(self.env['res.partner'].create({'name': 'Other'}))
        self.authenticate('couponer', 'couponer')
        page = self.url_open('/my/coupons').text
        self.assertIn('o_journey_newcoupon_modal', page, "new coupon: party popup")
        self.assertIn('You have a new coupon!', page)
        self.assertIn('o_journey_new_badge', page)
        self.assertTrue(self.make_jsonrpc_request('/my/coupons/celebrated', {'card_ids': [self.card.id, other.id]}))
        self.assertTrue(self.card.journey_celebrated)
        self.assertFalse(other.journey_celebrated, "not a coupon of this customer")
        page = self.url_open('/my/coupons').text
        self.assertIn(self.card.code, page)
        self.assertNotIn('o_journey_newcoupon_modal', page, "once per coupon")
        self.assertNotIn('o_journey_new_badge', page)

    def test_new_coupon_on_order_page_popup(self):
        self.env['sale.order'].create({
            'partner_id': self.user.partner_id.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.unit.id, 'product_uom_qty': 10})],
        })
        self.authenticate('couponer', 'couponer')
        page = self.url_open('/shop/order').text
        self.assertIn('data-new-card-ids="[%s]"' % self.card.id, page)
        self.card.journey_celebrated = True
        self.assertIn('data-new-card-ids="[]"', self.url_open('/shop/order').text)

    def test_order_page_link(self):
        self.authenticate('couponer', 'couponer')
        self.env['sale.order'].create({
            'partner_id': self.user.partner_id.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.unit.id, 'product_uom_qty': 10})],
        })
        page = self.url_open('/shop/order').text
        self.assertIn('href="/my/coupons"', page)
        self.assertEqual(self.url_open('/my/coupons').status_code, 200, "the link of the order page works")


@tagged('post_install', '-at_install')
class TestAddressSheet(OrderCommon):
    """View cart asks for the delivery address first ("Address details" of the v2 prototype)."""

    FORM = {
        'apartment': 'Apt 1204, Floor 12', 'building': 'Silver Wave Tower', 'directions': 'Parking B2',
        'label': 'work', 'name': 'Sara Receiver', 'phone': '+971501112233',
        'area': 'Al Zahiyah', 'city': 'Abu Dhabi', 'state': 'Abu Dhabi', 'country_code': 'AE',
    }

    def _cart(self):
        self.make_jsonrpc_request('/shop/cart/add', {
            'product_template_id': self.unit.product_tmpl_id.id, 'product_id': self.unit.id, 'quantity': 2})
        return self.env['sale.order'].search([('website_id', '=', self.website.id)], order='id desc', limit=1)

    def _pin(self, lat=24.4539, lng=54.3773):
        self.make_jsonrpc_request('/shop/journey/set_location', {'latitude': lat, 'longitude': lng, 'area': 'Al Zahiyah'})

    def _save(self, **changes):
        return self.make_jsonrpc_request('/shop/journey/address', dict(self.FORM, **changes))

    def test_guest_address(self):
        self.authenticate(None, None)
        order = self._cart()
        self.assertTrue(self.make_jsonrpc_request('/shop/journey/cart_total', {})['needs_address'])
        self._pin()
        page = self.url_open('/shop').text
        self.assertIn('data-needs-address="1"', page)
        self.assertIn('o_journey_address_modal', page)
        self.assertIn('Al Zahiyah', page, "the pin of the Deliver to bar")

        self.assertEqual(self._save(apartment=' ')['field'], 'apartment')
        self.assertEqual(self._save(building='')['field'], 'building')
        self.assertEqual(self._save(phone='')['field'], 'phone')
        self.assertEqual(order.partner_id, self.website.user_id.partner_id, "nothing saved while the form has errors")

        self.assertTrue(self._save()['ok'])
        address = order.partner_shipping_id
        self.assertEqual(order.partner_id, address, "a guest: the address is the customer too")
        self.assertEqual(order.partner_invoice_id, address)
        self.assertEqual(address.street, 'Apt 1204, Floor 12, Silver Wave Tower')
        self.assertEqual(address.street2, 'Al Zahiyah')
        self.assertEqual((address.city, address.country_id.code, address.zip), ('Abu Dhabi', 'AE', '00000'))
        self.assertEqual(address.state_id.name, 'Abu Dhabi')
        self.assertEqual(address.name, 'Sara Receiver')
        self.assertEqual(address.phone.replace(' ', ''), '+971501112233')
        self.assertEqual((address.address_label, address.delivery_directions), ('work', 'Parking B2'))
        self.assertAlmostEqual(address.partner_latitude, 24.4539)
        self.assertAlmostEqual(address.partner_longitude, 54.3773)

        self.assertFalse(self.make_jsonrpc_request('/shop/journey/cart_total', {})['needs_address'])
        page = self.url_open('/shop/order').text
        self.assertEqual(order.carrier_id, self.island, "delivery method of the zone of the pin")
        self.assertIn('Silver Wave Tower', page)
        self.assertIn('Delivered today within 3 hours', page)

    def test_receiver_mobile_is_a_real_number(self):
        self.authenticate(None, None)
        order = self._cart()
        self._pin()
        for wrong in ('12w3e4567', '5456', '123456', '02 123 4567', '+91 86062 91751', '+44 7700 900123'):
            result = self._save(phone=wrong)
            self.assertEqual(result['field'], 'phone', "%s is not a UAE mobile number" % wrong)
            self.assertIn('050 123 4567', result['error'], "an example of the right number")
        self.assertEqual(order.partner_id, self.website.user_id.partner_id, "nothing saved")

        for typed, stored in (('0501112233', '+971 50 111 2233'), ('50 111 2233', '+971 50 111 2233'),
                              ('971501112233', '+971 50 111 2233'), ('00971 50 111 2233', '+971 50 111 2233'),
                              ('+971 56 525 1911', '+971 56 525 1911')):
            self.assertTrue(self._save(phone=typed).get('ok'), typed)
            self.assertEqual(order.partner_shipping_id.phone, stored, "stored with its country code")

    def test_pin_is_required_and_in_a_zone(self):
        self.authenticate(None, None)
        self._cart()
        self.assertEqual(self._save()['field'], 'pin', "no location yet")
        self._pin(10.0, 10.0)
        self.assertEqual(self._save()['field'], 'pin', "outside the delivery zones")

    def test_without_map_details(self):
        """No Google Maps: city, emirate and country come from the company."""
        self.authenticate(None, None)
        order = self._cart()
        self._pin()
        self.website.company_id.write({
            'city': 'Abu Dhabi', 'country_id': self.env.ref('base.ae').id,
            'state_id': self.env['res.country.state'].search(
                [('country_id.code', '=', 'AE'), ('name', '=', 'Abu Dhabi')], limit=1).id,
        })
        self.assertTrue(self._save(area='', city='', state='', country_code='')['ok'])
        address = order.partner_shipping_id
        self.assertEqual((address.city, address.country_id.code, address.state_id.name),
                         ('Abu Dhabi', 'AE', 'Abu Dhabi'))
        self.assertEqual(address.street2, 'Abu Dhabi Island', "the zone when the area is unknown")

    def test_member_first_address(self):
        user = new_test_user(self.env, login='sheet', groups='base.group_portal', email='sheet@example.com')
        user.partner_id.name = 'Sara Receiver'
        self.authenticate('sheet', 'sheet')
        order = self._cart()
        self._pin()
        self.assertIn('value="Sara Receiver"', self.url_open('/shop').text, "the receiver starts with the customer")
        self.assertTrue(self._save()['ok'])
        self.assertEqual(order.partner_id, user.partner_id)
        self.assertEqual(order.partner_shipping_id, user.partner_id, "same receiver: the account address")
        self.assertEqual(user.partner_id.street, 'Apt 1204, Floor 12, Silver Wave Tower', "also the billing address")
        self.assertEqual(user.partner_id.phone.replace(' ', ''), '+971501112233')

    def test_member_other_receiver(self):
        user = new_test_user(self.env, login='gift', groups='base.group_portal', email='gift@example.com')
        user.partner_id.phone = '+971500000009'
        self.authenticate('gift', 'gift')
        order = self._cart()
        self._pin()
        self.assertTrue(self._save()['ok'])
        shipping = order.partner_shipping_id
        self.assertNotEqual(shipping, user.partner_id, "someone else receives it: a delivery address")
        self.assertEqual((shipping.parent_id, shipping.type), (user.partner_id, 'delivery'))
        self.assertEqual((shipping.name, shipping.email), ('Sara Receiver', 'gift@example.com'))
        self.assertEqual(shipping.phone.replace(' ', ''), '+971501112233')
        self.assertEqual(user.partner_id.phone, '+971500000009', "the customer's own mobile is kept")
        self.assertTrue(user.partner_id.street, "the first address is also the billing address")

    def test_change_an_address(self):
        """Change on the order page: the sheet shows the address, saving changes it."""
        self.authenticate(None, None)
        order = self._cart()
        self._pin()
        self._save()
        address = order.partner_shipping_id
        with MockRequest(self.env, website=self.website):
            data = json.loads(self.website._journey_address_data(address))
        self.assertEqual((data['apartment'], data['building']), ('Apt 1204, Floor 12', 'Silver Wave Tower'),
                         "the last part of the street is the building")
        self.assertEqual((data['label'], data['area'], data['partner_id']), ('work', 'Al Zahiyah', address.id))
        page = self.url_open('/shop/order').text
        self.assertIn('o_journey_address_open', page, "Change opens the sheet")
        self.assertIn('o_journey_address_modal', page)

        result = self._save(partner_id=address.id, apartment='Villa 7', name='Omar',
                            latitude=24.46, longitude=54.38, area='Al Khalidiyah')
        self.assertTrue(result['ok'])
        self.assertEqual(order.partner_shipping_id, address, "the same address, changed")
        self.assertEqual((address.street, address.street2, address.name), ('Villa 7, Silver Wave Tower', 'Al Khalidiyah', 'Omar'))
        self.assertAlmostEqual(address.partner_latitude, 24.46)

    def test_cannot_change_someone_elses_address(self):
        other = self.env['res.partner'].create({'name': 'Someone', 'street': 'Elsewhere'})
        self.authenticate(None, None)
        self._cart()
        self._pin()
        result = self._save(partner_id=other.id)
        self.assertNotIn('ok', result)
        self.assertEqual(other.street, 'Elsewhere')
