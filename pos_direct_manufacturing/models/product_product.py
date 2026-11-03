import re

from odoo import api, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def search_pos_raw_materials(self, config_id, search_term, limit=20, with_count=False):
        """Search products for the POS raw material popup.

        Restricted to storable (inventory-tracked) products only —
        not services or combos. Stock quantity is not checked here.

        When the POS has a Raw Material Category set, only products in
        that category or one of its subcategories are listed.

        The search term is split into words and every word must match,
        in any order, against the name, internal reference or barcode:
        "global" lists every Global Meats item, "global farm" narrows
        that down to the ones that also mention farm.

        The unit of measure is returned alongside each product so the popup
        can convert quantities before comparing the raw material total
        against the quantity sold, and skip that comparison when the units
        are not convertible into each other.
        """
        domain = [('is_storable', '=', True)]

        config = self.env['pos.config'].browse(config_id).exists()
        if config.raw_material_categ_id:
            domain.append(('categ_id', 'child_of', config.raw_material_categ_id.id))

        for word in self._split_raw_material_search(search_term):
            domain += [
                '|', '|',
                ('name', 'ilike', word),
                ('default_code', 'ilike', word),
                ('barcode', 'ilike', word),
            ]

        products = self.search(domain, limit=limit)
        result = [
            {
                'id': product.id,
                'display_name': product._raw_material_label(),
                'uom_id': product.uom_id.id,
                'uom_name': product.uom_id.name,
            }
            for product in products
        ]
        # A till still running the POS cached before an update calls this
        # without with_count and expects the plain list: keep answering it
        # that way so the popup does not break until the till is reloaded.
        if not with_count:
            return result
        return {
            # Shown in the popup as "Showing 50 of 298", so the cashier
            # knows when to keep typing instead of scrolling.
            'total': self.search_count(domain),
            'products': result,
        }

    @api.model
    def _split_raw_material_search(self, search_term):
        """Words of the search, each of which must match.

        Spaces, ",", "&", "+", ";", "|" and a standalone "and" all
        separate words, so "striploin chilled", "striploin, chilled" and
        "striploin and chilled" give the same result. "/" is not a
        separator: names use it in "B/I", "sm/off" and "kg/Ctn", and
        splitting "B/I" into "b" and "i" would match almost everything."""
        words = re.split(r'[\s,&+;|]+', search_term or '')
        return [w for w in words if w and w.lower() != 'and']

    def _raw_material_label(self):
        """"[00172] Bison Ribeye", or just the name when the internal
        reference is blank: display_name prints "[ ]" for a reference
        that is only whitespace, which looks like a missing value.

        The variant's attribute values stay in the label, otherwise the
        variants of one template would look like duplicates."""
        self.ensure_one()
        name = self.with_context(display_default_code=False).display_name
        code = (self.default_code or '').strip()
        return f'[{code}] {name}' if code else name
