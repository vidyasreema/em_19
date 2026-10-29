from odoo import Command
from odoo.tests import tagged

from odoo.addons.website_sale.tests.common import WebsiteSaleCommon


@tagged('post_install', '-at_install')
class TestFirstOrderNextOrderCoupon(WebsiteSaleCommon):
    """"First Order Only" on Next Order Coupons: only the first order earns the
    coupon, and the coupon can still be used on the second order."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'New Customer', 'email': 'new.customer@example.com'})
        cls.coupon_product = cls.env['product.product'].create({
            'name': 'Ribeye', 'list_price': 100, 'sale_ok': True, 'website_published': True})
        cls.program = cls.env['loyalty.program'].create({
            'name': 'Next order 10%',
            'program_type': 'next_order_coupons',
            'trigger': 'auto',
            'applies_on': 'future',
            'first_order_only': True,
            'rule_ids': [Command.create({'minimum_qty': 1, 'reward_point_amount': 1, 'reward_point_mode': 'order'})],
            'reward_ids': [Command.create({
                'reward_type': 'discount', 'discount': 10, 'discount_mode': 'percent',
                'discount_applicability': 'order', 'required_points': 1})],
        })

    def _order(self):
        return self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.coupon_product.id, 'product_uom_qty': 1})],
        })

    def test_only_the_first_order_earns_the_coupon(self):
        first = self._order()
        first.action_confirm()
        coupon = first.coupon_point_ids.coupon_id
        self.assertEqual(len(coupon), 1, "the first order earns a coupon")

        second = self._order()
        second._update_programs_and_rewards()
        self.assertFalse(second.coupon_point_ids.filtered('points'), "the second order earns nothing")
        coupon.points = 1  # given (at the delivery of the first order)
        result = second._try_apply_code(coupon.code)
        self.assertNotIn('error', result)
        second._apply_program_reward(self.program.reward_ids, coupon)
        self.assertTrue(second.order_line.filtered('is_reward_line'), "the coupon is used on the second order")
        second.action_confirm()
        self.assertEqual(second.state, 'sale')
        self.assertEqual(coupon.points, 0, "one use")
        self.assertFalse(
            self.env['loyalty.card'].search([('program_id', '=', self.program.id), ('id', '!=', coupon.id),
                                             ('points', '>', 0)]),
            "no new coupon for the next orders")

    def test_backend_order_can_use_the_coupon(self):
        first = self._order()
        first.website_id = False
        first.action_confirm()
        coupon = first.coupon_point_ids.coupon_id
        self.assertEqual(coupon.points, 1)
        second = self._order()
        second.website_id = False
        second._try_apply_code(coupon.code)
        second._apply_program_reward(self.program.reward_ids, coupon)
        second.action_confirm()  # no "first-order promotion" error
        self.assertEqual(second.state, 'sale')
