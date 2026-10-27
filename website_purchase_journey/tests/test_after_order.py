from odoo import Command, http
from odoo.http import root
from odoo.tests import new_test_user, tagged

from .test_order import OrderCommon


@tagged('post_install', '-at_install')
class TestAfterOrder(OrderCommon):
    """Version 2 §4: sign up after ordering; C6: tracking bar in the shop."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website.auth_signup_uninvited = 'b2c'

    def _guest_order(self, email='guest.after@example.com'):
        order = self._order(420, self.island, self._address(24.4539, 54.3773, name='Guest After', email=email))
        order.action_confirm()
        return order

    def _guest_session(self, order=None):
        session = self.authenticate(None, None)
        if order:
            session['sale_last_order_id'] = order.id
            root.session_store.save(session)
        return session

    def _sign_up(self):
        return self.url_open('/shop/order/signup', data={'csrf_token': http.Request.csrf_token(self)})

    def _next_order_program(self, minimum=300):
        self.env['loyalty.program'].search([('program_type', '=', 'next_order_coupons')]).active = False
        return self.env['loyalty.program'].create({
            'name': 'Next Order 10%', 'program_type': 'next_order_coupons', 'trigger': 'auto',
            'applies_on': 'future',
            'rule_ids': [Command.create({'minimum_amount': minimum, 'reward_point_mode': 'order', 'reward_point_amount': 1})],
            'reward_ids': [Command.create({
                'reward_type': 'discount', 'discount': 10, 'discount_mode': 'percent',
                'discount_applicability': 'order', 'required_points': 1, 'description': '10% off your order'})],
        })

    def _coupon_order(self, amount, confirm=True):
        order = self._order(amount, self.island, self._address(24.4539, 54.3773, name='Coupon Guest', email='coupon.guest@example.com'))
        order._update_programs_and_rewards()
        if confirm:
            order.action_confirm()
        self._guest_session(order)
        return order

    def test_next_order_coupon_on_confirmation(self):
        self._next_order_program()
        order = self._coupon_order(420)
        coupon = order.coupon_point_ids.coupon_id
        self.assertEqual(len(coupon), 1)
        page = self.url_open('/shop/confirmation').text
        self.assertIn('You earned a coupon for your next order', page)
        self.assertIn('10% off your order', page)
        self.assertIn(coupon.code, page, "ready: the code is shown")
        self.assertIn('coupon.guest@example.com', page, "guests: saved for their email")
        self.assertIn('o_journey_coupon_modal', page, "the Congratulations popup")
        self.assertIn('Congratulations!', page)

    def test_next_order_coupon_waits_for_payment(self):
        self._next_order_program()
        order = self._coupon_order(420, confirm=False)
        coupon = order.coupon_point_ids.coupon_id
        page = self.url_open('/shop/confirmation').text
        self.assertIn('You earned a coupon for your next order', page)
        self.assertIn('Ready once this order is paid.', page)
        self.assertNotIn(coupon.code, page, "no code before the payment")

    def test_no_next_order_coupon_below_minimum(self):
        self._next_order_program(minimum=1000)
        self._coupon_order(420)
        page = self.url_open('/shop/confirmation').text
        self.assertNotIn('o_journey_next_coupon', page)
        self.assertNotIn('o_journey_coupon_modal', page, "no popup")

    def test_confirmation_addresses_compact(self):
        order = self._guest_order()
        self._guest_session(order)
        page = self.url_open('/shop/confirmation').text
        self.assertIn('o_journey_conf_addresses', page, "one small box")
        self.assertNotIn('id="delivery_and_billing"', page, "instead of Odoo's tall card")
        self.assertIn('Guest After', page)
        self.assertIn('Tower A, Apt 5, Abu Dhabi, United Arab Emirates', page, "the address on one line")

        self.website.journey_enabled = False
        self.assertIn('id="delivery_and_billing"', self.url_open('/shop/confirmation').text)

    # ── Sign up from the confirmation page ────────────────────────────────

    def test_guest_signs_up_after_ordering(self):
        order = self._guest_order()
        self._guest_session(order)
        page = self.url_open('/shop/confirmation').text
        self.assertIn('Create an account to track this order and get 10% off your next order', page)
        self.assertIn('guest.after@example.com', page, "the email of the order")
        self.assertNotIn('to follow your order', page, "instead of Odoo's sign-up box")

        response = self._sign_up()
        self.assertIn('journey_signup=done', response.url)
        self.assertIn('Your account is created', response.text)
        self.assertNotIn('o_journey_post_signup_btn', response.text, "no second offer")

        user = self.env['res.users'].search([('login', '=', 'guest.after@example.com')])
        self.assertEqual(user.partner_id, order.partner_id, "the order is in the new account's orders")
        self.assertTrue(user._is_portal())
        card = self.env['loyalty.card'].search([('program_id', '=', self.welcome.id), ('partner_id', '=', user.partner_id.id)])
        self.assertEqual(len(card), 1, "the welcome coupon is in My coupons")

        self._sign_up()
        self.assertEqual(self.env['res.users'].search_count([('login', '=', 'guest.after@example.com')]), 1)

    def test_no_offer_when_the_email_has_an_account(self):
        new_test_user(self.env, login='taken@example.com', email='taken@example.com', groups='base.group_portal')
        order = self._guest_order(email='taken@example.com')
        self._guest_session(order)
        page = self.url_open('/shop/confirmation').text
        self.assertNotIn('o_journey_post_signup_btn', page)
        self.assertIn('You already have an account', page, "sign in instead")
        self._sign_up()
        self.assertFalse(order.partner_id.user_ids, "nothing created")

    def test_no_offer_when_sign_up_is_closed(self):
        self.website.auth_signup_uninvited = 'b2b'  # "On invitation" (per website)
        self._guest_session(self._guest_order())
        self.assertNotIn('o_journey_post_signup_btn', self.url_open('/shop/confirmation').text)

    def test_without_welcome_program(self):
        self.welcome.active = False
        self._guest_session(self._guest_order())
        page = self.url_open('/shop/confirmation').text
        self.assertIn('Create an account to track this order', page)
        self.assertNotIn('10% off your next order', page)

    # ── Tracking bar ───────────────────────────────────────────────────────

    def test_tracking_bar_member(self):
        user = new_test_user(self.env, login='tracker', groups='base.group_portal')
        order = self._order(420, self.island, user.partner_id)
        self.authenticate('tracker', 'tracker')
        self.assertNotIn('o_journey_track_bar', self.url_open('/shop').text, "the cart is not an order yet")

        order.action_confirm()
        page = self.url_open('/shop').text
        self.assertIn('o_journey_track_bar', page)
        self.assertIn(order.name, page)
        self.assertIn('Order received', page, "status from the Online Orders stage")
        self.assertIn('href="/my/orders/%s/track"' % order.id, page, "Track opens the order status")

        order._action_cancel()
        self.assertNotIn('o_journey_track_bar', self.url_open('/shop').text, "closed orders are not tracked")

    def test_tracking_bar_guest(self):
        order = self._guest_order()
        order._portal_ensure_token()
        self._guest_session(order)
        page = self.url_open('/shop').text
        self.assertIn(order.name, page)
        self.assertIn('/my/orders/%s/track?access_token=%s' % (order.id, order.access_token), page)

        self._guest_session()
        self.assertNotIn('o_journey_track_bar', self.url_open('/shop').text, "another visitor")

    def test_tracking_bar_switched_off(self):
        self.website.journey_enabled = False
        self._guest_session(self._guest_order())
        self.assertNotIn('o_journey_track_bar', self.url_open('/shop').text)

    def test_tracking_bar_on_every_page(self):
        user = new_test_user(self.env, login='everywhere', groups='base.group_portal')
        order = self._order(420, self.island, user.partner_id)
        order.action_confirm()
        self.authenticate('everywhere', 'everywhere')
        for path in ('/', '/contactus', '/my', '/my/orders', '/my/orders/%s' % order.id):
            self.assertIn('o_journey_track_bar', self.url_open(path).text, "shown on %s" % path)
        self.assertNotIn('o_journey_track_bar', self.url_open('/my/orders/%s/track' % order.id).text,
                         "not on the Track page itself")

        self._set_stage(order, 'out_for_delivery')
        self.assertIn('o_journey_track_bar', self.url_open('/').text, "until it is delivered")
        self._set_stage(order, 'delivered')
        self.assertNotIn('o_journey_track_bar', self.url_open('/').text, "gone once delivered")

    # ── Track / Order details, Order again (C6, C7) ──────────────────────

    def _set_stage(self, order, code):
        """Stage straight in the database: the stage rules (delivery validation...)
        are tested in Online Orders."""
        stage = self.env['online.order.stage']._get_by_code(code)
        self.env.cr.execute("UPDATE sale_order SET stage_id = %s WHERE id = %s", (stage.id, order.id))
        order.invalidate_recordset(['stage_id'])

    def _member_order(self):
        user = new_test_user(self.env, login='trackpage', groups='base.group_portal')
        order = self._order(420, self.island, user.partner_id)
        order.action_confirm()
        self.authenticate('trackpage', 'trackpage')
        return order

    def test_track_page_steps(self):
        order = self._member_order()
        page = self.url_open('/my/orders/%s/track' % order.id).text
        self.assertIn('Track your order', page)
        self.assertIn('TOUR Mince (unit)', page)
        self.assertIn('Promised:', page)
        self.assertEqual(page.count('o_journey_track_step_on'), 1, "Order received")
        self.assertIn('o_journey_reorder', page)

        self._set_stage(order, 'out_for_delivery')
        page = self.url_open('/my/orders/%s/track' % order.id).text
        self.assertEqual(page.count('o_journey_track_step_on'), 2)

        self._set_stage(order, 'completed')
        page = self.url_open('/my/orders/%s/track' % order.id).text
        self.assertIn('Order details', page, "after delivery")
        self.assertEqual(page.count('o_journey_track_step_on'), 3)
        self.assertNotIn('Promised:', page)

        self._set_stage(order, 'cancelled')
        self.assertIn('Order cancelled', self.url_open('/my/orders/%s/track' % order.id).text)

    def test_my_orders_buttons(self):
        order = self._member_order()
        page = self.url_open('/my/orders').text
        self.assertIn('/my/orders/%s/track' % order.id, page)
        self.assertIn('Order again', page)
        self._set_stage(order, 'delivered')
        self.assertIn('View details', self.url_open('/my/orders').text)
        page = self.url_open('/my/orders/%s' % order.id).text
        self.assertIn('o_journey_reorder', page, "Odoo's order page: our Order again")
        self.assertNotIn('reorder_sidebar_button', page, "instead of Odoo's (it only adds)")
        self.assertNotIn('o_journey_track_btn', page, "delivered: no Track button on the order page")

    def test_track_page_access(self):
        order = self._guest_order()
        order._portal_ensure_token()
        self._guest_session()
        page = self.url_open('/my/orders/%s/track?access_token=%s' % (order.id, order.access_token)).text
        self.assertIn('Track your order', page, "guests: with the order link")
        response = self.url_open('/my/orders/%s/track?access_token=wrong' % order.id)
        self.assertNotIn('Track your order', response.text)

    def test_order_again_skips_out_of_stock(self):
        sold_out = self.env['product.product'].create({
            'name': 'TOUR Sold out', 'list_price': 5.0, 'type': 'consu', 'is_published': True,
            'website_ribbon_id': self.out_of_stock.id,
        })
        order = self._member_order()
        order.order_line = [Command.create({'product_id': sold_out.id, 'product_uom_qty': 1})]
        result = self.make_jsonrpc_request('/my/orders/reorder', {'order_id': order.id})
        self.assertEqual(result['cart_quantity'], 420)
        cart = self.env['sale.order'].search([('partner_id', '=', order.partner_id.id), ('state', '=', 'draft')])
        self.assertEqual(cart.order_line.product_id, self.unit, "the out-of-stock product is not added again")

    def test_order_again_with_a_cart(self):
        order = self._member_order()
        other = self.env['product.product'].create({'name': 'TOUR Other', 'list_price': 2.0, 'is_published': True})
        params = {'order_id': order.id}

        result = self.make_jsonrpc_request('/shop/order/reorder', {**params, 'mode': 'ask'})
        self.assertEqual(result['cart_quantity'], 420, "empty cart: no question")
        cart = self.env['sale.order'].search([('partner_id', '=', order.partner_id.id), ('state', '=', 'draft')])
        cart.order_line = [Command.create({'product_id': other.id, 'product_uom_qty': 1})]

        result = self.make_jsonrpc_request('/shop/order/reorder', {**params, 'mode': 'ask'})
        self.assertTrue(result.get('ask'), "products in the cart: the customer chooses")
        self.assertEqual(cart.order_line.filtered(lambda l: l.product_id == self.unit).product_uom_qty, 420, "nothing changed yet")

        self.make_jsonrpc_request('/shop/order/reorder', {**params, 'mode': 'add'})
        lines = cart._journey_product_lines()
        self.assertEqual(lines.filtered(lambda l: l.product_id == self.unit).product_uom_qty, 840, "added")
        self.assertIn(other, lines.product_id)

        self.make_jsonrpc_request('/shop/order/reorder', {**params, 'mode': 'replace'})
        lines = cart._journey_product_lines()
        self.assertEqual(lines.product_id, self.unit, "replaced: only the products of the order")
        self.assertEqual(lines.product_uom_qty, 420, "with its quantities")

    def test_order_again_someone_elses_order(self):
        order = self._guest_order()
        self.authenticate(None, None)
        result = self.make_jsonrpc_request('/shop/order/reorder', {'order_id': order.id, 'mode': 'replace'})
        self.assertTrue(result.get('error'))
