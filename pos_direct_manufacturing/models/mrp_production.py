from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    pos_order_id = fields.Many2one(
        'pos.order',
        string='Source POS Order',
        copy=False,
        index=True,
        help="The POS order that triggered creation of this Manufacturing "
             "Order. Set automatically — not meant to be edited manually.",
    )