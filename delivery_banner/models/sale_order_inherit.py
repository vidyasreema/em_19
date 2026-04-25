from odoo import models, fields, api
from datetime import date
from dateutil.relativedelta import relativedelta


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    banner_delivery_date_label = fields.Char(
        string='Delivery Date Label',
        compute='_compute_banner_fields',
        store=False,
    )

    banner_delivery_type_label = fields.Char(
        string='Delivery Type Label',
        compute='_compute_banner_fields',
        store=False,
    )

    # ── Add state to depends ─────────────────────────────
    @api.depends('commitment_date', 'carrier_id', 'state')
    def _compute_banner_fields(self):
        today = fields.Date.context_today(self)
        for order in self:

            # ── Delivery Date Label (always normal) ──────────
            if order.commitment_date:
                delivery_date = order.commitment_date.date()
                if delivery_date == today:
                    order.banner_delivery_date_label = 'Today'
                elif delivery_date == today + relativedelta(days=1):
                    order.banner_delivery_date_label = 'Tomorrow'
                else:
                    order.banner_delivery_date_label = (
                        order.commitment_date.strftime(
                            '%d %b %Y · %H:%M'
                        )
                    )
            else:
                order.banner_delivery_date_label = 'Not Set'

            # ── Delivery Type Label ───────────────────────────
            # If delivered → show delivered label
            if order.state == 'delivered':
                order.banner_delivery_type_label = (
                    '✅ Order Delivered'
                )

            # Otherwise → show carrier type
            elif order.carrier_id:
                carrier_name = order.carrier_id.name or ''
                if any(x in carrier_name.lower() for x in [
                    'pick up', 'pickup', 'collect'
                ]):
                    order.banner_delivery_type_label = (
                        '🏪 Pick Up In Store'
                    )
                else:
                    order.banner_delivery_type_label = (
                        '🚚 Delivery'
                    )
            else:
                order.banner_delivery_type_label = 'Not Set'