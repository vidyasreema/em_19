from odoo import fields, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    # Marks lines created by the "Show Zero-Stock Products" option, so that
    # turning the option off only removes our own untouched lines.
    zero_option_line = fields.Boolean(
        string='Created by Zero-Stock Option',
        default=False,
        copy=False,
        index=True,
    )
