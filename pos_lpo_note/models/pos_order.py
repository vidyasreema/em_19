from odoo import fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    lpo_number = fields.Char(
        string="LPO Number",
        copy=False,
        help="Customer's Local Purchase Order / reference number for this order.",
    )

    def _order_fields(self, ui_order):
        order_fields = super()._order_fields(ui_order)
        order_fields["lpo_number"] = ui_order.get("lpo_number")
        return order_fields

    def _prepare_invoice_vals(self):
        vals = super()._prepare_invoice_vals()
        vals["lpo_number"] = self.lpo_number
        return vals
