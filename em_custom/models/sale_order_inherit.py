from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ════════════════════════════════════════════════════
    # Override state field to add 'delivered'
    # ════════════════════════════════════════════════════
    state = fields.Selection(
        selection_add=[
            ('delivered', 'Delivered'),
        ],
        ondelete={'delivered': 'set default'}
    )

    # ════════════════════════════════════════════════════
    # Compute button visibility
    # Shows only when order is confirmed + pending delivery
    # ════════════════════════════════════════════════════
    delivery_button_visible = fields.Boolean(
        string='Show Deliver Button',
        compute='_compute_delivery_button_visible',
        store=False
    )

    @api.depends('picking_ids', 'picking_ids.state', 'state')
    def _compute_delivery_button_visible(self):
        for order in self:
            pending = order.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
                and p.picking_type_code == 'outgoing'
            )
            # Show only when sale order confirmed
            # and has pending delivery
            order.delivery_button_visible = (
                bool(pending)
                and order.state == 'sale'
            )

    # ════════════════════════════════════════════════════
    # BUTTON: Mark as Delivered
    # Validates delivery + sets state to delivered
    # ════════════════════════════════════════════════════
    def action_mark_as_delivered(self):
        for order in self:
            # ── Get pending outgoing deliveries ──────────
            pending_pickings = order.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
                and p.picking_type_code == 'outgoing'
            )

            if not pending_pickings:
                raise UserError(_(
                    'No pending deliveries found '
                    'for this order.'
                ))

            for picking in pending_pickings:

                # ── Odoo 18: Set qty on move lines ───────
                if picking.move_line_ids:
                    for move_line in picking.move_line_ids:
                        if move_line.state not in (
                            'done', 'cancel'
                        ):
                            # ✅ Odoo 18 correct field
                            move_line.qty_done = (
                                move_line.quantity
                            )
                else:
                    # Fallback: set on move level
                    for move in picking.move_ids:
                        if move.state not in (
                            'done', 'cancel'
                        ):
                            move.quantity = (
                                move.product_uom_qty
                            )

                # ── Validate with no backorder ───────────
                picking_to_validate = picking.with_context(
                    skip_backorder=True,
                    immediate_transfer=True,
                )
                res = picking_to_validate.button_validate()

                # ── Handle wizard if still appears ───────
                if isinstance(res, dict):
                    res_model = res.get('res_model', '')

                    if res_model == (
                        'stock.backorder.confirmation'
                    ):
                        wizard = self.env[res_model]\
                            .with_context(
                                **res.get('context', {})
                            ).create({
                                'pick_ids': [
                                    (4, picking.id)
                                ]
                            })
                        wizard.process_cancel_backorder()

                    elif res_model == (
                        'stock.immediate.transfer'
                    ):
                        wizard = self.env[res_model]\
                            .with_context(
                                **res.get('context', {})
                            ).create({
                                'pick_ids': [
                                    (4, picking.id)
                                ]
                            })
                        wizard.process()

            # ── Set order state to Delivered ─────────────
            order.write({'state': 'delivered'})

            # ── Log in chatter ───────────────────────────
            order.message_post(
                body=_(
                    '✅ Delivery marked as done by <b>%s</b>'
                ) % self.env.user.name,
                message_type='notification'
            )

        return True