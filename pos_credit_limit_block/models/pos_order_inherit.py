from odoo import api, models
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = "pos.order"

    # ⚠️ VERIFY the method name against your v19 source:
    # addons/point_of_sale/models/pos_order.py
    @api.model
    def sync_from_ui(self, orders):
        for order_vals in orders:
            self._check_pos_credit_limit(order_vals)
        return super().sync_from_ui(orders)

    @api.model
    def _check_pos_credit_limit(self, order_vals):
        partner_id = order_vals.get("partner_id")
        if not partner_id:
            return

        # Refunds carry a negative total. Never block them —
        # they reduce the customer's debt.
        if (order_vals.get("amount_total") or 0.0) < 0:
            return

        method_ids = []
        for command in order_vals.get("payment_ids") or []:
            # payment_ids arrives as ORM commands: [(0, 0, {...}), ...]
            if isinstance(command, (list, tuple)) and len(command) == 3:
                vals = command[2]
                if isinstance(vals, dict) and vals.get("payment_method_id"):
                    method_ids.append(vals["payment_method_id"])

        if not method_ids:
            return

        methods = self.env["pos.payment.method"].browse(method_ids)
        if not methods.filtered(lambda m: m.type == "pay_later"):
            return

        status = self.env["res.partner"].get_pos_credit_status(partner_id)
        if status.get("blocked"):
            raise UserError(status["message"])