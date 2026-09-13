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
    pos_order_line_id = fields.Many2one(
        'pos.order.line',
        string='Source POS Order Line',
        copy=False,
        index=True,
        help="The exact POS order line that triggered this Manufacturing "
             "Order. Used to trace refunds back to the correct MO when an "
             "order has several lines for the same manufactured product.",
    )