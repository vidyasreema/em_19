from odoo import fields, models
from odoo.fields import Domain

from odoo.addons.website_sale_meta_feed.models.product_feed import OUT_OF_STOCK_RIBBON_NAMES


class Website(models.Model):
    _inherit = 'website'

    online_orders_email_from = fields.Char(
        "Order emails from",
        help="Sender of the order emails of this shop (on the way, delivered, cancelled, address "
             "updated), e.g. The Cut <orders@thecutuae.com>. Empty: the email of the company.")

    # ── Product availability (Annex 4A) ─────────────────────────────────
    # The ribbon is the single source: the website, the Meta catalog (product
    # feed) and the Product Availability switch read the same ribbons.

    def _online_out_of_stock_ribbon(self):
        """The ribbon the availability switch puts on an out-of-stock product."""
        ribbon = self.env.ref('website_sale.out_of_stock_ribbon', raise_if_not_found=False)
        if not ribbon:
            ribbon = self.env['product.ribbon'].sudo().with_context(lang='en_US').search(
                [('name', '=ilike', OUT_OF_STOCK_RIBBON_NAMES[0])], limit=1)
        return ribbon.sudo()

    def _online_out_of_stock_ribbons(self):
        """Ribbons that mean "out of stock": the ones the product feed of this
        website sends as out of stock ("Out of stock" and "Sold out" by default),
        always including the ribbon written by the availability switch."""
        website = self or self.get_current_website()
        feeds = self.env['product.feed'].sudo().search([('website_id', '=', website.id)])
        ribbons = feeds.out_of_stock_ribbon_ids
        if not ribbons:
            ribbons = self.env['product.ribbon'].sudo().with_context(lang='en_US').search(Domain.OR(
                Domain('name', '=ilike', name) for name in OUT_OF_STOCK_RIBBON_NAMES))
        return ribbons | website._online_out_of_stock_ribbon()
