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

    def _get_pack_label(self):
        """Returns e.g. '2 × Carton 9 kg' if the line is a whole number of packs, else False."""
        self.ensure_one()
        pack = self.pack_uom_id
        base_uom = self.product_id.uom_id
        if not pack or not base_uom or not base_uom.factor:
            return False
        qty_per_pack = pack.factor / base_uom.factor
        if not qty_per_pack:
            return False
        packs = self.qty / qty_per_pack
        if abs(packs - round(packs)) > 0.0001 or round(packs) == 0:
            return False
        return f"{abs(round(packs))} × {pack.name}"

    def _prepare_base_line_for_taxes_computation(self):
        """Adds the pack to the line description, so it appears on the invoice."""
        base_line = super()._prepare_base_line_for_taxes_computation()
        label = self._get_pack_label()
        if label and base_line.get('name'):
            base_line['name'] = f"{base_line['name']} ({label})"
        return base_line