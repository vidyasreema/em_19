from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.online_order_stage import CLOSED_CODES
from ..models.sale_order import CANCEL_REASONS


class OnlineOrderCancelWizard(models.TransientModel):
    _name = 'online.order.cancel.wizard'
    _description = 'Cancel Online Order'

    order_id = fields.Many2one('sale.order', required=True, readonly=True)
    reason = fields.Selection(CANCEL_REASONS, string='Reason', required=True)
    note = fields.Text('Note')

    def action_cancel_order(self):
        """Standard Cancel of the order, with the reason. The order moves to
        Cancelled: the stage email is sent and Accounts get the refund activity."""
        self.ensure_one()
        order = self.order_id
        if order.stage_id.code in CLOSED_CODES:
            raise UserError(_("Order %(order)s is already %(stage)s.", order=order.name, stage=order.stage_id.name))
        order.write({'online_cancel_reason': self.reason, 'online_cancel_note': self.note})
        # Sudo: Sales staff have no Inventory / Accounting rights, but the standard
        # Cancel also cancels the delivery order and draft invoices.
        order_sudo = order.sudo()
        if order_sudo.locked:
            order_sudo.action_unlock()
        order_sudo.action_cancel()
        return {'type': 'ir.actions.act_window_close'}
