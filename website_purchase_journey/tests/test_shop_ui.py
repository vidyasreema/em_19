from odoo.tests import tagged

from .common import JourneyCommon


@tagged('post_install', '-at_install')
class TestJourneyShopUi(JourneyCommon):

    def test_shop_tour(self):
        self.multi.attribute_line_ids[0].product_template_value_ids.filtered(
            lambda v: v.name == '250 g').ptav_product_variant_ids.variant_ribbon_id = self.out_of_stock
        self.start_tour('/shop', 'journey_shop')
        order = self.env['sale.order'].search([('website_id', '=', self.website.id)], order='id desc', limit=1)
        lines = order.order_line.filtered(lambda l: l.product_id.product_tmpl_id in (self.multi | self.single))
        self.assertEqual(len(lines), 3, "two weights of the ribeye (two lines) and the sausages")
        self.assertEqual(sorted(lines.mapped('price_unit')), [40.0, 60.0, 100.0])


@tagged('post_install', '-at_install')
class TestJourneyOrderUi(JourneyCommon):

    def test_order_tour(self):
        from odoo import Command
        from odoo.tests import new_test_user
        # Same-day popup (on for every method since 19.0.3.2.0)
        self.island.write({'free_over': True, 'amount': 400.0, 'website_published': True, 'show_popup_scenario_1': True})
        self.env['delivery.carrier'].search([('id', '!=', self.island.id)]).active = False
        unit = self.env['product.product'].create({
            'name': 'TOUR Mince (unit)', 'list_price': 1.0, 'type': 'consu', 'is_published': True,
            'sale_ok': True, 'taxes_id': [Command.clear()],
        })
        user = new_test_user(self.env, login='tourbuyer', groups='base.group_portal', email='tourbuyer@example.com')
        user.partner_id.write({
            'street': 'Tower A', 'street2': 'Apt 5', 'city': 'Abu Dhabi', 'country_id': self.env.ref('base.ae').id,
            'phone': '+971500000001', 'partner_latitude': 24.4539, 'partner_longitude': 54.3773,
        })
        welcome = self.env.ref('website_purchase_journey.loyalty_program_welcome_signup')
        self.website.journey_welcome_program_id = welcome
        welcome._journey_give_welcome_coupon(user.partner_id)
        order = self.env['sale.order'].create({
            'partner_id': user.partner_id.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': unit.id, 'product_uom_qty': 380})],
        })
        # One payment method, always available (like "Pay on site")
        self.env['payment.provider'].search([('code', '!=', 'none')]).state = 'disabled'
        self.env.ref('payment.payment_provider_transfer').write({'state': 'enabled', 'is_published': True})
        self.start_tour('/shop/order', 'journey_order', login='tourbuyer')
        self.assertIn(order.state, ('sent', 'sale'), "the order was placed")
        self.assertTrue(order.delivery_call_on_arrival)
        self.assertFalse(order.delivery_leave_at_door, "no Leave at my door option")
        self.assertEqual(order.order_note, 'Gate 2, then the lift')
        self.assertTrue(user.partner_id.marketing_consent)
        self.assertEqual(order.order_line.filtered('is_reward_line').reward_id.program_id, welcome)
        self.assertTrue(order.delivery_promise_until, "the promise was stored when paying")
        self.assertEqual(order.carrier_id, self.island)
        self.assertEqual(order.partner_shipping_id.name, 'Mona Gift', "changed from the Address details sheet")
        self.assertEqual(order.partner_shipping_id.street, 'Apt 5, Tower A')
        self.assertNotEqual(user.partner_id.name, 'Mona Gift', "the account keeps its name")

    def test_order_guest_tour(self):
        self.island.write({'free_over': True, 'amount': 400.0, 'website_published': True})
        self.website.journey_welcome_program_id = self.env.ref('website_purchase_journey.loyalty_program_welcome_signup')
        self.env['payment.provider'].search([('code', '!=', 'none')]).state = 'disabled'
        self.env.ref('payment.payment_provider_transfer').write({'state': 'enabled', 'is_published': True})
        self.start_tour('/shop', 'journey_order_guest')


@tagged('post_install', '-at_install')
class TestJourneyTrackUi(JourneyCommon):

    def test_track_tour(self):
        from odoo import Command
        from odoo.tests import new_test_user
        user = new_test_user(self.env, login='tracktour', groups='base.group_portal', email='tracktour@example.com')
        unit = self.env['product.product'].create({
            'name': 'TOUR Mince (unit)', 'list_price': 1.0, 'type': 'consu', 'is_published': True,
            'sale_ok': True, 'taxes_id': [Command.clear()],
        })
        order = self.env['sale.order'].create({
            'partner_id': user.partner_id.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': unit.id, 'product_uom_qty': 3})],
        })
        order.action_confirm()
        self.start_tour('/my/orders', 'journey_track', login='tracktour')
        cart = self.env['sale.order'].search([('partner_id', '=', user.partner_id.id), ('state', '=', 'draft')])
        self.assertEqual(cart.order_line.filtered(lambda l: l.product_id == unit).product_uom_qty, 3)
