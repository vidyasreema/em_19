from odoo import fields, models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    raw_material_ids = fields.One2many(
        'pos.order.line.raw.material',
        'order_line_id',
        string='Raw Materials Used',
        help="Raw materials and quantities selected for this order line "
             "at the point of sale. Populated from the POS popup.",
    )

    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        fields_list.append('raw_material_ids')
        return fields_list

    def save_raw_materials(self, material_lines):
        """Kept for potential manual/backend use; not used in the main
        POS flow, since raw materials are created client-side and
        synced automatically via the order line's own _load_pos_data_fields.
        """
        self.ensure_one()
        self.raw_material_ids.unlink()
        for line in material_lines:
            self.env['pos.order.line.raw.material'].create({
                'order_line_id': self.id,
                'product_id': line['product_id'],
                'qty': line['qty'],
            })
        return True