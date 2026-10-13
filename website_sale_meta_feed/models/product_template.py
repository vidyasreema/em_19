from odoo import api, models

# Template fields sent in the product feed: a change resets the feed cache.
FEED_TEMPLATE_FIELDS = {
    'name', 'active', 'is_published', 'website_id', 'sale_ok', 'type',
    'list_price', 'default_code', 'barcode', 'image_1920',
    'website_ribbon_id', 'description_ecommerce', 'website_meta_description',
    'description_sale', 'allow_out_of_stock_order', 'is_storable',
    'attribute_line_ids', 'public_categ_ids', 'product_tag_ids',
}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        if templates.filtered('is_published'):
            self.env['product.feed']._invalidate_all_feed_caches()
        return templates

    def write(self, vals):
        res = super().write(vals)
        if FEED_TEMPLATE_FIELDS.intersection(vals):
            self.env['product.feed']._invalidate_all_feed_caches()
        return res
