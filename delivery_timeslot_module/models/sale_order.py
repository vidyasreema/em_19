# -*- coding: utf-8 -*-
import pytz

from odoo import api, fields, models

from .delivery_carrier import PROMISE_TYPES, float_to_time_str


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    delivery_promise_type = fields.Selection(
        PROMISE_TYPES,
        string='Delivery Promise Type',
        readonly=True,
        copy=False,
    )
    delivery_promise_message = fields.Char(
        string='Delivery Promise',
        readonly=True,
        copy=False,
        help='Message shown to the customer when the order was placed.',
    )
    delivery_promise_from = fields.Datetime(
        string='Promised From',
        readonly=True,
        copy=False,
    )
    delivery_promise_until = fields.Datetime(
        string='Promised By',
        readonly=True,
        copy=False,
        help='The order is on time if delivered (or ready for pickup) before this time.',
    )

    delivery_promise_date_label = fields.Char(
        string='Promised Date',
        compute='_compute_delivery_promise_date_label',
        help="Date and time of the promise, e.g. 'Thu 22 Oct · 12:00 PM – 10:00 PM'.",
    )

    @api.depends('delivery_promise_from', 'delivery_promise_until', 'delivery_promise_type', 'website_id')
    def _compute_delivery_promise_date_label(self):
        Carrier = self.env['delivery.carrier']
        for order in self:
            if not order.delivery_promise_until:
                order.delivery_promise_date_label = False
                continue
            settings = self.env['store.settings'].sudo()._find_for_website(order.website_id)
            tz = settings._get_timezone() if settings else pytz.timezone('Asia/Dubai')
            local_from, local_until = (
                pytz.utc.localize(dt).astimezone(tz)
                for dt in (order.delivery_promise_from or order.delivery_promise_until, order.delivery_promise_until))
            window = None if order.delivery_promise_type == 'same_day' else (local_from, local_until)
            order.delivery_promise_date_label = Carrier._promise_date_label(
                local_until.date(), window,
                float_to_time_str(local_from.hour + local_from.minute / 60.0),
                float_to_time_str(local_until.hour + local_until.minute / 60.0))

    def _get_delivery_promise(self, now=None):
        """Promise of the order's delivery method at `now` ({} if none)."""
        self.ensure_one()
        if not self.carrier_id:
            return {}
        settings = self.env['store.settings'].sudo()._find_for_website(self.website_id)
        if not settings:
            return {}
        return self.carrier_id._get_delivery_promise(settings, now=now)

    def _store_delivery_promise(self, now=None):
        """Save the promise on the order. The Delivery Date (commitment_date)
        is the promised time, so the delivery order is scheduled for it."""
        for order in self:
            promise = order._get_delivery_promise(now=now)
            if not promise:
                continue
            order.write({
                'delivery_promise_type': promise['promise_type'],
                'delivery_promise_message': promise['message'],
                'delivery_promise_from': promise['promised_from'],
                'delivery_promise_until': promise['promised_until'],
                'commitment_date': promise['promised_until'],
            })

    def action_confirm(self):
        # Website orders get their promise when the customer pays; this covers
        # the other ways an order is confirmed (e.g. without online payment).
        self.filtered(
            lambda o: o.website_id and o.state in ('draft', 'sent') and not o.delivery_promise_until
        )._store_delivery_promise()
        return super().action_confirm()
