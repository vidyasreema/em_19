from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    pack_uom_id = fields.Many2one(
        'uom.uom',
        string='Pack',
        help="The pack this line was sold as (for example Carton 9 kg). Empty for loose sales.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['pack_uom_id']