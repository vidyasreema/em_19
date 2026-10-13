import re

from lxml import html as lxml_html

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools import is_html_empty

# Default ribbons that mean the product is not available.
OUT_OF_STOCK_RIBBON_NAMES = ('Out of stock', 'Sold out')
BRAND_ATTRIBUTE_NAME = 'brand'
DESCRIPTION_MAX_LENGTH = 5000  # Google's limit (Meta allows 9999)
# HTML elements that end a line of text.
BLOCK_TAGS = ('p', 'div', 'br', 'li', 'tr', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote')


def html_to_text(value):
    """Plain text of an HTML field: words separated by single spaces, nothing
    added inside a sentence (unlike `text_from_html`, which spaces out bold text)."""
    if is_html_empty(value):
        return ''
    tree = lxml_html.fragment_fromstring(str(value), create_parent='div')
    for node in tree.xpath('//script|//style'):
        node.drop_tree()
    for node in tree.iter(*BLOCK_TAGS):
        node.tail = ' ' + (node.tail or '')
    return re.sub(r'\s+', ' ', tree.text_content()).strip()


class ProductFeed(models.Model):
    _inherit = 'product.feed'

    out_of_stock_ribbon_ids = fields.Many2many(
        'product.ribbon',
        string="Out-of-Stock Ribbons",
        compute='_compute_out_of_stock_ribbon_ids',
        store=True,
        readonly=False,
        help="Products with one of these ribbons are sent as out of stock;"
        " all other products are sent as in stock.",
    )

    @api.depends('website_id')
    def _compute_out_of_stock_ribbon_ids(self):
        ribbons = self.env['product.ribbon'].with_context(lang='en_US').search(Domain.OR(
            Domain('name', '=ilike', name) for name in OUT_OF_STOCK_RIBBON_NAMES
        ))
        for feed in self.filtered(lambda f: not f.out_of_stock_ribbon_ids):
            feed.out_of_stock_ribbon_ids = ribbons

    def write(self, vals):
        res = super().write(vals)
        if 'out_of_stock_ribbon_ids' in vals:
            self.action_invalidate_cache()
        return res

    @api.model
    def _invalidate_all_feed_caches(self):
        """Reset the cache of every feed still holding a rendered XML, so product
        changes reach Meta / Google on their next sync instead of the next day."""
        self.sudo().search([('cache_expiry', '>', fields.Datetime.now())]).action_invalidate_cache()

    def _prepare_gmc_items(self):
        items = super()._prepare_gmc_items()
        for product, item in items.items():
            item['condition'] = 'new'
            item['description'] = self._get_meta_description(product, item['title'])
            if brand := self._get_meta_brand(product):
                item['brand'] = brand
        return items

    def _prepare_gmc_stock_info(self, product):
        """Availability comes from the ribbon (products are sold out of stock, so the
        quantity is not reliable). The core stock check is kept for products that
        cannot be sold out of stock. Values are written with a space ("in stock"),
        the format of Meta, also accepted by Google."""
        stock_info = super()._prepare_gmc_stock_info(product)
        ribbon = product.variant_ribbon_id or product.product_tmpl_id.website_ribbon_id
        out_of_stock = (
            stock_info.get('availability') == 'out_of_stock'
            or (ribbon and ribbon in self.out_of_stock_ribbon_ids)
        )
        stock_info['availability'] = 'out of stock' if out_of_stock else 'in stock'
        return stock_info

    def _get_meta_description(self, product, title):
        """Plain-text eCommerce description, never empty (Meta rejects products
        without a description)."""
        description = (
            html_to_text(product.description_ecommerce)
            or product.website_meta_description
            or product.description_sale
            or title
            or product.name
        )
        return description.strip()[:DESCRIPTION_MAX_LENGTH]

    def _get_meta_brand(self, product):
        """Value of the product's Brand attribute (variant value first, then a
        single-value attribute line of the template)."""
        def is_brand(attribute):
            name = attribute.with_context(lang='en_US').name or ''
            return name.strip().lower() == BRAND_ATTRIBUTE_NAME

        ptav = product.product_template_attribute_value_ids.filtered(
            lambda v: is_brand(v.attribute_id))[:1]
        if ptav:
            return ptav.name
        line = product.product_tmpl_id.attribute_line_ids.filtered(
            lambda l: is_brand(l.attribute_id) and len(l.value_ids) == 1)[:1]
        return line.value_ids.name or ''
