from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    pos_order_id = fields.Many2one(
        'pos.order',
        string='Source POS Order',
        copy=False,
        index=True,
        help="The POS order that triggered creation of this Manufacturing "
             "Order. Set automatically — not meant to be edited manually.",
    )
    pos_order_line_id = fields.Many2one(
        'pos.order.line',
        string='Source POS Order Line',
        copy=False,
        index=True,
        help="The exact POS order line that triggered this Manufacturing "
             "Order. Used to trace refunds back to the correct MO when an "
             "order has several lines for the same manufactured product.",
    )


    pos_invoice_id = fields.Many2one(
        'account.move',
        string='POS Invoice',
        related='pos_order_id.account_move',
        readonly=True,
    )


    def action_view_pos_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'POS Order',
            'res_model': 'pos.order',
            'res_id': self.pos_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


    def action_view_pos_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoice',
            'res_model': 'account.move',
            'res_id': self.pos_invoice_id.id,
            'view_mode': 'form',
            'context': {'default_move_type': 'out_invoice'},
            'target': 'current',
        }