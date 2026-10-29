from odoo import fields, models


class StockScrap(models.Model):
    _inherit = 'stock.scrap'

    barcode_register_logged = fields.Boolean(copy=False, readonly=True, index=True)
