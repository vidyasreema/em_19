from odoo import api, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _get_invoice_lines_values(self, line_values, pos_line, move_type):
        """Pack lines are invoiced in the pack unit: e.g. 1 carton @ 99.00 instead of 9 kg @ 11.00."""
        vals = super()._get_invoice_lines_values(line_values, pos_line, move_type)
        pack = pos_line.pack_uom_id
        base_uom = pos_line.product_id.uom_id
        if not pack or vals.get('display_type') or not base_uom.factor:
            return vals
        qty_per_pack = pack.factor / base_uom.factor
        if not qty_per_pack:
            return vals
        packs = pos_line.qty / qty_per_pack
        if abs(packs - round(packs)) > 0.0001 or round(packs) == 0:
            return vals  # not a whole number of packs: keep the normal (base unit) line
        sign = 1 if vals.get('quantity', 0) >= 0 else -1
        currency = pos_line.order_id.currency_id
        vals.update({
            'product_uom_id': pack.id,
            'quantity': sign * abs(round(packs)),
            'price_unit': currency.round(line_values['price_unit'] * qty_per_pack),
        })
        return vals