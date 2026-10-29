from odoo import fields, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    count_session_id = fields.Many2one('stock.count.session', 'Count Session', readonly=True, copy=False,
                                       help="Count session that wrote the Counted quantity.")
    count_session_qty = fields.Float('Count Session Quantity', digits='Product Unit', readonly=True, copy=False,
                                     help="Counted quantity as posted by the count session.")

    def _get_inventory_move_values(self, qty, location_id, location_dest_id, package_id=False, package_dest_id=False):
        res = super()._get_inventory_move_values(qty, location_id, location_dest_id, package_id=package_id, package_dest_id=package_dest_id)
        if self.count_session_id:
            # A Counted value edited by hand after posting is logged as ADJ for that difference only
            res.update(
                count_session_id=self.count_session_id.id,
                count_session_diff=self.inventory_quantity - self.count_session_qty,
            )
        return res

    def _apply_inventory(self, date=None):
        sessions = self.count_session_id
        res = super()._apply_inventory(date=date)
        if sessions:
            sessions.sudo().apply_date = fields.Datetime.now()
        return res

    def action_clear_inventory_quantity(self):
        res = super().action_clear_inventory_quantity()
        self.sudo().write({'count_session_id': False, 'count_session_qty': 0})
        return res
