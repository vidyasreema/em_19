from functools import partial

from odoo.http import request

from odoo.addons.website_sale_loyalty.controllers.delivery import WebsiteSaleLoyaltyDelivery


class LoyaltyFirstOrderDelivery(WebsiteSaleLoyaltyDelivery):

    def _order_summary_values(self, order, **post):
        """When the delivery method changes, the checkout script rewrites the
        offer amounts in the summary. Send them in the same order and with the
        same tax display as the offer rows, so they don't jump to the untaxed
        amount and the page doesn't reload because the row count differs."""
        res = super()._order_summary_values(order, **post)
        to_html = partial(
            request.env['ir.qweb.field.monetary'].value_to_html,
            options={'display_currency': order.currency_id},
        )
        offer_lines = order._get_offer_summary_lines()
        res['discount_reward_amounts'] = [
            to_html(line._get_cart_display_price())
            for line in offer_lines if line.reward_id.reward_type == 'discount'
        ]
        shipping_lines = offer_lines.filtered(lambda l: l.reward_id.reward_type == 'shipping')
        if shipping_lines:
            res['amount_delivery_discounted'] = to_html(
                sum(line._get_cart_display_price() for line in shipping_lines))
        return res
