from odoo import api, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def search_pos_raw_materials(self, config_id, search_term, limit=20):
        """Search products for the POS raw material popup.

        Restricted to storable (inventory-tracked) products only —
        not services or combos. Stock quantity is not checked here.

        The unit of measure is returned alongside each product so the popup
        can convert quantities before comparing the raw material total
        against the quantity sold, and skip that comparison when the units
        are not convertible into each other.
        """
        domain = [('is_storable', '=', True)]
        if search_term:
            domain.append(('name', 'ilike', search_term))

        products = self.search(domain, limit=limit)

        return [
            {
                'id': product.id,
                'display_name': product.display_name,
                'uom_id': product.uom_id.id,
                'uom_name': product.uom_id.name,
            }
            for product in products
        ]