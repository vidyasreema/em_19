from odoo import models

# Variant fields sent in the product feed: a change resets the feed cache.
FEED_VARIANT_FIELDS = {
    'active', 'default_code', 'barcode', 'image_variant_1920',
    'variant_ribbon_id', 'product_template_attribute_value_ids',
}


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        res = super().write(vals)
        if FEED_VARIANT_FIELDS.intersection(vals):
            self.env['product.feed']._invalidate_all_feed_caches()
        return res
