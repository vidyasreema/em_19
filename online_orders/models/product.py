from odoo import fields, models

# Cost and margin hidden by access rights (Annex 4, section 5): only the
# "See Product Cost" group, given to the Sales, Inventory, Accounting,
# Purchase, Manufacturing and POS users, can read the cost.
COST_GROUPS = 'online_orders.group_product_cost'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    standard_price = fields.Float(groups=COST_GROUPS)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    standard_price = fields.Float(groups=COST_GROUPS)
