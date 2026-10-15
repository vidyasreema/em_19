from odoo import Command
from odoo.tests import tagged

from odoo.addons.loyalty_first_order.controllers.delivery import LoyaltyFirstOrderDelivery
from odoo.addons.website_sale.tests.common import MockRequest, WebsiteSaleCommon


@tagged('post_install', '-at_install')
class TestOrderSummary(WebsiteSaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website.show_line_subtotals_tax_selection = 'tax_included'
        tax = cls.env['account.tax'].create({'name': 'VAT 5%', 'amount': 5})
        cls.summary_product = cls.env['product.product'].create({
            'name': 'Ribeye', 'list_price': 100, 'taxes_id': [Command.set(tax.ids)],
            'sale_ok': True, 'website_published': True,
        })
        cls.program = cls.env['loyalty.program'].create({
            'name': 'Welcome 10%',
            'program_type': 'promotion',
            'trigger': 'auto',
            'applies_on': 'current',
            'rule_ids': [Command.create({})],
            'reward_ids': [Command.create({
                'reward_type': 'discount', 'discount': 10,
                'discount_mode': 'percent', 'discount_applicability': 'order',
            })],
        })

    def _order_with_offer(self):
        order = self.empty_cart
        order.order_line = [Command.create({'product_id': self.summary_product.id, 'product_uom_qty': 2})]
        order._update_programs_and_rewards()
        order._auto_apply_rewards()
        self.assertTrue(order.order_line.reward_id, "the promotion should apply")
        return order

    def test_offer_rows_add_up_to_total(self):
        order = self._order_with_offer()
        offers = order._get_offer_summary_lines()
        self.assertEqual(len(offers), 1)
        # Tax-included website: 2 x 105 = 210, offer -21
        self.assertAlmostEqual(order._get_items_summary_amount(), 210)
        self.assertAlmostEqual(offers._get_cart_display_price(), -21)
        self.assertAlmostEqual(
            order._get_items_summary_amount() + offers._get_cart_display_price(), order.amount_total)

    def test_no_offer_rows_without_offer(self):
        order = self.empty_cart
        order.order_line = [Command.create({'product_id': self.summary_product.id, 'product_uom_qty': 1})]
        self.program.active = False
        order._update_programs_and_rewards()
        self.assertFalse(order._get_offer_summary_lines())
        with MockRequest(self.env, website=self.website, sale_order_id=order.id):
            html = self.env['ir.qweb']._render(
                'website_sale.total', {'website_sale_order': order, 'hide_promotions': True})
        self.assertNotIn('o_order_offer', str(html))

    def test_summary_shows_offer_once(self):
        order = self._order_with_offer()
        offer_name = order._get_offer_summary_lines()._get_line_header()
        with MockRequest(self.env, website=self.website, sale_order_id=order.id):
            total = str(self.env['ir.qweb']._render(
                'website_sale.total', {'website_sale_order': order, 'hide_promotions': True}))
            items = str(self.env['ir.qweb']._render(
                'website_sale.cart_summary_content', {'website_sale_order': order}))
        self.assertIn('name="o_order_items"', total)
        self.assertIn('name="o_order_offer"', total)
        self.assertIn(offer_name, total)
        self.assertIn('data-reward-type="discount"', total)
        self.assertNotIn(offer_name, items, "the offer must not be listed again among the items")
        self.assertIn(self.summary_product.name, items)

    def test_delivery_change_amounts_match_rows(self):
        order = self._order_with_offer()
        with MockRequest(self.env, website=self.website, sale_order_id=order.id):
            values = LoyaltyFirstOrderDelivery()._order_summary_values(order)
        self.assertEqual(len(values['discount_reward_amounts']), 1)
        # tax-included amount, as shown in the row (not the untaxed -20.00)
        self.assertIn('21.00', values['discount_reward_amounts'][0])
