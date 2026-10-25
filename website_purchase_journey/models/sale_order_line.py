from odoo import models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _is_reorder_allowed(self):
        """Order again: skip the products with the Out of stock ribbon (the
        single source of availability, Annex 3 §9)."""
        website = self.order_id.website_id
        if website.journey_enabled and self.product_id and self.product_id.product_tmpl_id._journey_is_out_of_stock(
                website, self.product_id):
            return False
        return super()._is_reorder_allowed()
