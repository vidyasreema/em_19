from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    lpo_number = fields.Char(
        string="LPO Number",
        copy=False,
        help="Customer's Local Purchase Order / reference number, carried over from the POS order.",
    )
