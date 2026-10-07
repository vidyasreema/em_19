from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    pack_price_ids = fields.One2many(
        'product.pricelist.item',
        'product_tmpl_id',
        string='Pack Prices',
        domain=[('pack_uom_id', '!=', False)],
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['uom_ids']