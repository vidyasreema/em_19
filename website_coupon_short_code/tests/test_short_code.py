from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.online_orders.tests.common import OnlineOrdersCommon


@tagged('post_install', '-at_install')
class TestShortCode(OnlineOrdersCommon):
    """One short code per coupon programme, shown instead of the long codes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['loyalty.program'].search([('program_type', '=', 'next_order_coupons')]).active = False
        cls.program = cls.env['loyalty.program'].create({
            'name': 'Next order 10%', 'program_type': 'next_order_coupons', 'trigger': 'auto',
            'applies_on': 'future', 'short_code': 'second10',
            'rule_ids': [Command.create({'minimum_qty': 1, 'reward_point_amount': 1, 'reward_point_mode': 'order'})],
            'reward_ids': [Command.create({'reward_type': 'discount', 'discount': 10, 'required_points': 1})],
        })
        cls.coupon = cls.env['loyalty.card'].create({'program_id': cls.program.id, 'partner_id': cls.customer.id, 'points': 1})
        cls.other = cls.env['res.partner'].create({'name': 'Other customer', 'email': 'other@example.com'})

    def _cart(self, partner):
        return self.env['sale.order'].create({
            'partner_id': partner.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.meat.id, 'product_uom_qty': 1})],
        })

    def test_short_code_is_shown(self):
        self.assertEqual(self.program.short_code, 'SECOND10', "kept in capitals")
        current, _past = self.env['loyalty.card']._journey_portal_coupons(self.customer)
        self.assertEqual([c['code'] for c in current], ['SECOND10'], "My coupons: not the long code")

    def test_typed_code_applies_own_coupon(self):
        status = self._cart(self.customer)._try_apply_code('second10')
        self.assertNotIn('error', status)
        self.assertEqual(next(iter(status)), self.coupon, "the customer's own coupon")

    def test_code_of_someone_else(self):
        self.assertEqual(self._cart(self.other)._try_apply_code('SECOND10').get('error'), "You don't have this coupon.")

    def test_used_coupon(self):
        self.coupon.points = 0
        self.assertEqual(self._cart(self.customer)._try_apply_code('SECOND10').get('error'), "You don't have this coupon.")

    def test_long_code_still_works(self):
        self.assertNotIn('error', self._cart(self.customer)._try_apply_code(self.coupon.code))

    def test_coupon_that_expires_first(self):
        later = self.env['loyalty.card'].create({
            'program_id': self.program.id, 'partner_id': self.customer.id, 'points': 1, 'expiration_date': '2099-01-01'})
        self.coupon.expiration_date = '2098-01-01'
        self.assertEqual(self._cart(self.customer)._short_code_coupon(self.program), self.coupon)
        self.assertTrue(later)

    def test_earned_coupon_and_delivered_email(self):
        order = self._create_order(partner=self.other)
        self.assertEqual(order._journey_next_order_coupon()['code'], 'SECOND10')
        order.action_online_next_stage()
        order.action_online_next_stage()
        self.assertEqual(order.online_next_order_coupons, 'SECOND10', "the Delivered email shows the short code")

    def test_empty_short_code_keeps_long_code(self):
        self.program.short_code = False
        current, _past = self.env['loyalty.card']._journey_portal_coupons(self.customer)
        self.assertEqual(current[0]['code'], self.coupon.code)

    def test_short_code_cannot_be_a_real_code(self):
        promo = self.env['loyalty.program'].create({
            'name': 'Promo', 'program_type': 'promo_code', 'trigger': 'with_code',
            'rule_ids': [Command.create({'code': 'VIP20'})],
            'reward_ids': [Command.create({'reward_type': 'discount', 'discount': 20})],
        })
        with self.assertRaises(ValidationError):
            self.program.short_code = 'vip20'
        with self.assertRaises(ValidationError):
            promo.rule_ids.code = 'SECOND10'
        with self.assertRaises(ValidationError):
            promo.short_code = 'PROMO10'  # not a coupon programme
        with self.assertRaises(ValidationError):
            self.program.copy({'short_code': 'SECOND10'})
