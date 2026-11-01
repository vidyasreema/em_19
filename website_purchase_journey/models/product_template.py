from odoo import models
from odoo.http import request


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _journey_variant_prices(self, website):
        """Website price of each variant (pricelist and tax display of the
        website), computed like the price of the shop tile."""
        self.ensure_one()
        variants = self.product_variant_ids
        pricelist = request.pricelist
        fiscal_position = request.fiscal_position
        currency = website.currency_id
        rule_prices = pricelist._compute_price_rule(variants, 1.0)
        prices = {}
        for variant in variants:
            product_taxes = variant.sudo().taxes_id._filter_taxes_by_company(self.env.company)
            taxes = fiscal_position.map_tax(product_taxes)
            prices[variant] = self._apply_taxes_to_price(
                rule_prices[variant.id][0], currency, product_taxes, taxes, variant, website=website)
        return prices

    def _journey_is_out_of_stock(self, website, variant=None):
        """Out of stock ribbon, of the variant first, then of the product (like the feed)."""
        ribbons = website._journey_out_of_stock_ribbons()
        ribbon = (variant and variant.variant_ribbon_id) or self.website_ribbon_id
        return bool(ribbon) and ribbon in ribbons

    def _journey_tile_info(self, website):
        """Values of the product card: button, "from" price, quantity in the cart."""
        self.ensure_one()
        variants = self.product_variant_ids
        multi = len(variants) > 1
        info = {
            'multi': multi,
            'variant': variants[:1],
            'out_of_stock': self._journey_is_out_of_stock(website, None if multi else variants[:1]),
            'from_price': None,
            'show_from': False,
            'cart_qty': website._journey_cart_quantities()['templates'].get(self.id, 0),
        }
        if multi:
            prices = list(self._journey_variant_prices(website).values())
            info['from_price'] = min(prices)
            info['show_from'] = website.currency_id.compare_amounts(max(prices), min(prices)) > 0
        return info

    def _journey_variant_label(self, variant):
        """'450g': values of the attributes that differ between the variants."""
        values = variant.product_template_attribute_value_ids.filtered(
            lambda ptav: len(ptav.attribute_line_id.value_ids) > 1)
        return ' · '.join(values.mapped('name')) or variant.display_name

    def _journey_weight_rows(self, website):
        """Rows of the weight sheet, cheapest first."""
        self.ensure_one()
        prices = self._journey_variant_prices(website)
        cart = website._journey_cart_quantities()['variants']
        template_out_of_stock = self._journey_is_out_of_stock(website)
        rows = [{
            'variant': variant,
            'label': self._journey_variant_label(variant),
            'price': price,
            'out_of_stock': template_out_of_stock or self._journey_is_out_of_stock(website, variant),
            'cart_qty': cart.get(variant.id, 0),
        } for variant, price in prices.items()]
        return sorted(rows, key=lambda row: (row['price'], row['label']))
