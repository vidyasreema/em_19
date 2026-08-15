from odoo import api, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def search_pos_raw_materials(self, config_id, search_term, limit=20):
        """Search products for the POS raw material popup.

        Restricted to storable (inventory-tracked) products only —
        not services or combos. Stock quantity is not checked here.
        """
        domain = [('is_storable', '=', True)]
        if search_term:
            domain.append(('name', 'ilike', search_term))

        products = self.search(domain, limit=limit)

        return [
            {'id': product.id, 'display_name': product.display_name}
            for product in products
        ]