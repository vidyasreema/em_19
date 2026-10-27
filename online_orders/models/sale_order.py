from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.misc import format_date

from .online_order_stage import CLOSED_CODES

CANCEL_REASONS = [
    ('address', 'Wrong address / unreachable'),
    ('customer', 'Customer request'),
    ('unavailable', 'Product unavailable'),
    ('other', 'Other'),
]
# Card badge: an open order whose promise ends within this time
SOON_MINUTES = 45
# Card stripe (kanban colors): Purple for today, Blue for scheduled
DAY_COLOR_TODAY = 5
DAY_COLOR_SCHEDULED = 8


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Named stage_id so the standard Automation Rule trigger "Stage is set to" works on it.
    stage_id = fields.Many2one(
        'online.order.stage',
        string='Online Order Stage',
        tracking=True,
        index=True,
        copy=False,
        ondelete='restrict',
        group_expand='_read_group_stage_ids',
    )
    stage_code = fields.Selection(related='stage_id.code', string='Stage Role', tracking=False)

    # ─── Times ────────────────────────────────────────────────────────────────
    online_out_for_delivery_date = fields.Datetime('Out for Delivery At', readonly=True, copy=False)
    online_delivered_date = fields.Datetime('Delivered At', readonly=True, copy=False)
    online_completed_date = fields.Datetime('Completed At', readonly=True, copy=False)
    online_cancel_date = fields.Datetime('Cancelled At', readonly=True, copy=False)
    online_cancel_reason = fields.Selection(CANCEL_REASONS, string='Cancellation Reason', readonly=True, copy=False)
    online_cancel_note = fields.Text('Cancellation Note', readonly=True, copy=False)

    # ─── Delivery quality (stored for Pivot / Graph) ────────────────────────────
    # The measures are readable by Marketing and Management only (access rights):
    # Sales never see the quality report, even by opening its URL.
    online_zone_id = fields.Many2one('delivery.zone', string='Delivery Zone', readonly=True, copy=False, index=True)
    online_order_hour = fields.Integer(
        'Order Hour', compute='_compute_online_order_hour', store=True, aggregator=False,
        help='Hour of the day the order was placed (Abu Dhabi time).')
    online_delivery_minutes = fields.Integer(
        'Delivery Duration (min)', compute='_compute_online_quality', store=True, aggregator='avg',
        groups='online_orders.group_online_orders_marketing,online_orders.group_online_orders_management',
        help='From the order to the delivery.')
    online_delay_minutes = fields.Integer(
        'Delay (min)', compute='_compute_online_quality', store=True, aggregator='avg',
        groups='online_orders.group_online_orders_marketing,online_orders.group_online_orders_management',
        help='Minutes delivered after the promised time (0 if on time).')
    online_on_time_rate = fields.Integer(
        'On-Time Rate (%)', compute='_compute_online_quality', store=True, aggregator='avg',
        groups='online_orders.group_online_orders_marketing,online_orders.group_online_orders_management',
        help='100 if delivered by the promised time, otherwise 0. Its average is the on-time rate.')

    # ─── Board ──────────────────────────────────────────────────────────────────
    online_time_status = fields.Selection(
        [('normal', 'On Time'), ('soon', 'Under 45 min'), ('late', 'Late'), ('done', 'Done')],
        string='Time Status', compute='_compute_online_time_status')
    online_is_late = fields.Boolean(
        'Overdue', compute='_compute_online_time_status', search='_search_online_is_late')
    online_next_stage_id = fields.Many2one(
        'online.order.stage', string='Next Stage', compute='_compute_online_next_stage_id')
    online_delivery_day = fields.Selection(
        [('past', 'Earlier'), ('today', 'Today'), ('scheduled', 'Scheduled')],
        string='Delivery Day', compute='_compute_online_delivery_day',
        help='Day of the promised delivery: today, or scheduled for a later day.')
    online_delivery_day_label = fields.Char('Delivery Day Label', compute='_compute_online_delivery_day')
    online_delivery_day_color = fields.Integer('Delivery Day Color', compute='_compute_online_delivery_day')

    # ─── Order page (dispatch through Careem) ───────────────────────────────────
    online_coordinates = fields.Char(related='partner_shipping_id.partner_coordinates', string='Coordinates', tracking=False)
    online_address_text = fields.Char('Address', compute='_compute_online_dispatch')
    online_address_label = fields.Selection(related='partner_shipping_id.address_label', string='Label', tracking=False)
    online_driver_notes = fields.Text(related='partner_shipping_id.delivery_directions', string='Driver Notes', tracking=False)
    online_receiver_name = fields.Char(related='partner_shipping_id.name', string='Receiver', tracking=False)
    online_receiver_phone = fields.Char(related='partner_shipping_id.phone', string='Receiver Mobile', tracking=False)
    online_customer_email = fields.Char(related='partner_id.email', string='Customer Email', tracking=False)
    online_area = fields.Char('Area', compute='_compute_online_dispatch')
    online_cash_to_collect = fields.Monetary('Cash to Collect', compute='_compute_online_dispatch')
    online_cash_to_collect_text = fields.Char('Cash to Collect (copy)', compute='_compute_online_dispatch')
    online_next_order_coupons = fields.Char('Next Order Coupons', compute='_compute_online_next_order_coupons')

    # ──────────────────────────────────────────────────────────────────────────
    # Computes
    # ──────────────────────────────────────────────────────────────────────────

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        """All columns on the board, even empty ones."""
        return stages.search([])

    def _online_timezone(self):
        settings = self.env['store.settings'].sudo()._find_for_website(self.website_id)
        return settings._get_timezone() if settings else pytz.timezone('Asia/Dubai')

    @api.depends('date_order', 'website_id')
    def _compute_online_order_hour(self):
        for order in self:
            if order.date_order:
                local = pytz.utc.localize(order.date_order).astimezone(order._online_timezone())
                order.online_order_hour = local.hour
            else:
                order.online_order_hour = 0

    @api.depends('online_delivered_date', 'date_order', 'delivery_promise_until')
    def _compute_online_quality(self):
        for order in self:
            delivered = order.online_delivered_date
            if not delivered:
                order.online_delivery_minutes = 0
                order.online_delay_minutes = 0
                order.online_on_time_rate = 0
                continue
            order.online_delivery_minutes = max(0, int((delivered - order.date_order).total_seconds() // 60))
            promised = order.delivery_promise_until
            late = bool(promised) and delivered > promised
            order.online_delay_minutes = int((delivered - promised).total_seconds() // 60) if late else 0
            order.online_on_time_rate = 0 if late else 100

    def _online_is_open(self):
        """On the board and not delivered yet."""
        self.ensure_one()
        return bool(self.stage_id) and not self.online_delivered_date \
            and self.stage_id.code not in ('delivered',) + CLOSED_CODES

    @api.depends('delivery_promise_until', 'stage_id', 'online_delivered_date')
    def _compute_online_time_status(self):
        now = fields.Datetime.now()
        for order in self:
            if not order._online_is_open():
                status = 'done'
            elif not order.delivery_promise_until:
                status = 'normal'
            elif order.delivery_promise_until < now:
                status = 'late'
            elif order.delivery_promise_until - now <= timedelta(minutes=SOON_MINUTES):
                status = 'soon'
            else:
                status = 'normal'
            order.online_time_status = status
            order.online_is_late = status == 'late'

    @api.depends('delivery_promise_until', 'commitment_date', 'website_id')
    def _compute_online_delivery_day(self):
        """Card badge: "Today", or "Scheduled" with its day (e.g. "Tomorrow, Sat 25 Oct")."""
        for order in self:
            promised = order.delivery_promise_until or order.commitment_date
            # Stripe on the left of the card: purple today, blue scheduled
            order.online_delivery_day_color = 0
            if not promised:
                order.online_delivery_day = False
                order.online_delivery_day_label = False
                continue
            tz = order._online_timezone()
            today = datetime.now(tz).date()
            day = pytz.utc.localize(promised).astimezone(tz).date()
            if day < today:
                order.online_delivery_day = 'past'
                order.online_delivery_day_label = False
            elif day == today:
                order.online_delivery_day = 'today'
                order.online_delivery_day_label = _("Today")
                order.online_delivery_day_color = DAY_COLOR_TODAY
            else:
                order.online_delivery_day = 'scheduled'
                order.online_delivery_day_color = DAY_COLOR_SCHEDULED
                date_text = format_date(self.env, day, date_format='EEE d MMM')
                order.online_delivery_day_label = (
                    _("Tomorrow, %s", date_text) if day == today + timedelta(days=1) else date_text)

    def _online_open_domain(self):
        return Domain([
            ('website_id', '!=', False),
            ('stage_id', '!=', False),
            ('online_delivered_date', '=', False),
            ('stage_id.code', 'not in', ('delivered',) + CLOSED_CODES),
        ])

    def _search_online_is_late(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        late = self._online_open_domain() & Domain('delivery_promise_until', '<', fields.Datetime.now())
        return late if (operator == '=') == value else ~late

    @api.depends('stage_id')
    def _compute_online_next_stage_id(self):
        """Next stage a person can move the order to (Completed and Cancelled excluded)."""
        stages = self.env['online.order.stage'].search([('code', 'not in', CLOSED_CODES)])
        for order in self:
            current = order.stage_id
            following = stages.filtered(
                lambda s: current and current.code not in CLOSED_CODES and s._position() > current._position())
            order.online_next_stage_id = following[:1]

    @api.depends('partner_shipping_id', 'amount_total', 'amount_paid')
    def _compute_online_dispatch(self):
        for order in self:
            address = order.partner_shipping_id
            order.online_address_text = ', '.join(filter(None, [
                address.street, address.street2, address.city, address.state_id.name]))
            order.online_area = address.city or address.state_id.name or ''
            cash = order.amount_total - order.sudo().amount_paid
            cash = cash if order.currency_id.compare_amounts(cash, 0) > 0 else 0.0
            order.online_cash_to_collect = cash
            order.online_cash_to_collect_text = '%.2f' % cash

    def _compute_online_next_order_coupons(self):
        for order in self:
            coupons = order.sudo().coupon_point_ids.coupon_id.filtered(
                lambda c: c.program_id.program_type == 'next_order_coupons')
            order.online_next_order_coupons = ', '.join(coupons.mapped('code'))

    # ──────────────────────────────────────────────────────────────────────────
    # Stage changes
    # ──────────────────────────────────────────────────────────────────────────

    def write(self, vals):
        if 'stage_id' not in vals:
            return super().write(vals)
        new_stage = self.env['online.order.stage'].browse(vals['stage_id'])
        for order in self:
            changed = order.stage_id != new_stage
            extra = order._online_prepare_stage_change(new_stage)
            super(SaleOrder, order).write(dict(vals, **extra))
            if changed:
                order._online_after_stage_change()
        return True

    def _online_prepare_stage_change(self, new_stage):
        """Check a move to `new_stage` and do what the stage requires.

        :return: values to write together with the stage (times)
        """
        self.ensure_one()
        old_stage = self.stage_id
        if old_stage == new_stage:
            return {}
        context = self.env.context
        if not new_stage:
            raise UserError(_("An online order cannot leave the board."))
        if not self.website_id:
            raise UserError(_("Only website orders can be moved on the Online Orders board."))
        if old_stage.code in CLOSED_CODES:
            raise UserError(_("Order %(order)s is %(stage)s: it cannot be moved anymore.",
                              order=self.name, stage=old_stage.name))
        if new_stage.code == 'cancelled' and not context.get('online_order_cancel'):
            raise UserError(_("Use the “Cancel order” button: a cancellation reason is required."))
        if new_stage.code == 'completed' and not context.get('online_order_auto_complete'):
            raise UserError(_("Orders move to Completed automatically after closing."))

        now = fields.Datetime.now()
        if new_stage.code == 'cancelled':
            return {'online_cancel_date': now}

        if self.state != 'sale':
            raise UserError(_("Order %s is not confirmed.", self.name))
        if old_stage and not new_stage._is_at_or_after(old_stage):
            raise UserError(_("Orders only move forward: %(old)s cannot go back to %(new)s.",
                              old=old_stage.name, new=new_stage.name))

        Stage = self.env['online.order.stage']
        extra = {}
        if new_stage._is_at_or_after(Stage._get_by_code('out_for_delivery')) \
                and not self.online_out_for_delivery_date:
            self._online_validate_delivery()
            extra['online_out_for_delivery_date'] = now
        if new_stage._is_at_or_after(Stage._get_by_code('delivered')) and not self.online_delivered_date:
            extra['online_delivered_date'] = now
        if new_stage.code == 'completed':
            extra['online_completed_date'] = now
        return extra

    def _online_validate_delivery(self):
        """Validate the delivery order(s): the stock leaves when the driver does.
        Any problem (e.g. a missing lot) stops the move with the reason."""
        self.ensure_one()
        # Sudo: Sales staff have no Inventory rights; the user is still recorded.
        pickings = self.sudo().picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state not in ('done', 'cancel'))
        for picking in pickings:
            picking._online_set_delivered_by()
            if picking.state == 'draft':
                picking.action_confirm()
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                move.quantity = move.product_uom_qty
                move.picked = True
            result = picking.with_context(
                skip_backorder=True, picking_ids_not_to_backorder=picking.ids,
            ).button_validate()
            if picking.state != 'done':
                raise UserError(_(
                    "The delivery order %(picking)s could not be validated, so the order "
                    "was not moved. Please check it in Inventory.", picking=picking.name)
                    if result is True else _(
                    "The delivery order %(picking)s needs more information before it can be "
                    "validated (e.g. lots or quantities). Please complete it in Inventory.",
                    picking=picking.name))

    def _track_template(self, changes):
        """Email of the stage (like Project / Helpdesk stages)."""
        res = super()._track_template(changes)
        order = self[:1]
        if 'stage_id' in changes and order.stage_id.mail_template_id:
            res['stage_id'] = (order.stage_id.mail_template_id, {
                'auto_delete_keep_log': False,
                'subtype_id': self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note'),
                'email_layout_xmlid': 'mail.mail_notification_light',
            })
        return res

    def _online_after_stage_change(self):
        """Activity of the new stage (e.g. refund for Accounts on Cancelled)."""
        for order in self:
            stage = order.stage_id
            if stage.activity_user_id:
                order.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=stage.activity_summary or stage.name,
                    note=order.online_cancel_note if stage.code == 'cancelled' else False,
                    user_id=stage.activity_user_id.id,
                )

    def _online_set_stage(self, stage):
        self.write({'stage_id': stage.id})

    # ──────────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────────

    def action_online_next_stage(self):
        for order in self:
            if not order.online_next_stage_id:
                raise UserError(_("There is no next stage for %s: Completed is set automatically.", order.name))
            order._online_set_stage(order.online_next_stage_id)
        return True

    def action_online_cancel_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cancel Order'),
            'res_model': 'online.order.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def action_confirm(self):
        res = super().action_confirm()
        new_stage = self.env['online.order.stage'].sudo()._get_by_code('new')
        for order in self.filtered(lambda o: o.website_id and not o.stage_id and o.state == 'sale'):
            order.online_zone_id = order._online_find_zone()
            if new_stage:
                order._online_set_stage(new_stage)
        return res

    def _action_cancel(self):
        """Any cancellation of an order on the board moves it to Cancelled."""
        res = super()._action_cancel()
        cancel_stage = self.env['online.order.stage'].sudo()._get_by_code('cancelled')
        orders = self.filtered(lambda o: o.stage_id and o.stage_id != cancel_stage)
        if cancel_stage and orders:
            orders.with_context(online_order_cancel=True)._online_set_stage(cancel_stage)
        return res

    def _online_find_zone(self):
        self.ensure_one()
        address = self.partner_shipping_id
        if not (address.partner_latitude and address.partner_longitude):
            return self.env['delivery.zone']
        zones = self.env['delivery.zone'].sudo().search([('active', '=', True), ('polygon', '!=', False)])
        for zone in zones:
            if zone.is_location_in_zone(address.partner_latitude, address.partner_longitude):
                return zone
        return self.env['delivery.zone']

    @api.model
    def _cron_online_orders_complete(self):
        """After closing: every delivered order goes to Completed (board archive)."""
        Stage = self.env['online.order.stage']
        delivered, completed = Stage._get_by_code('delivered'), Stage._get_by_code('completed')
        if not (delivered and completed):
            return
        stages = Stage.search([('code', 'not in', CLOSED_CODES)]).filtered(
            lambda s: s._is_at_or_after(delivered) and not s._is_at_or_after(completed))
        orders = self.search([('stage_id', 'in', stages.ids)])
        orders.with_context(online_order_auto_complete=True).write({'stage_id': completed.id})

    @api.model
    def get_online_order_counters(self):
        """Counters on top of the board."""
        tz = self._online_timezone()
        today = datetime.now(tz).date()
        start = tz.localize(datetime.combine(today, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        open_domain = self._online_open_domain()
        return {
            'open': self.search_count(open_domain),
            'overdue': self.search_count(open_domain & Domain('delivery_promise_until', '<', fields.Datetime.now())),
            'delivered_today': self.search_count([
                ('website_id', '!=', False), ('online_delivered_date', '>=', start)]),
        }

    @api.model
    def _online_orders_init_existing_orders(self):
        """Install: put the existing confirmed / cancelled website orders on the board.
        Delivered (delivery order done) -> Completed, others -> New, cancelled -> Cancelled."""
        Stage = self.env['online.order.stage']
        orders = self.search([('website_id', '!=', False), ('stage_id', '=', False),
                              ('state', 'in', ('sale', 'cancel'))])
        stage_by_code = {code: Stage._get_by_code(code) for code in ('new', 'completed', 'cancelled')}
        for order in orders:
            outgoing = order.picking_ids.filtered(lambda p: p.picking_type_code == 'outgoing')
            if order.state == 'cancel':
                code = 'cancelled'
            elif outgoing and all(p.state in ('done', 'cancel') for p in outgoing):
                code = 'completed'
            else:
                code = 'new'
            # Initial placement: no checks, no emails, no stock moves
            super(SaleOrder, order.with_context(tracking_disable=True)).write({
                'stage_id': stage_by_code[code].id,
                'online_zone_id': order._online_find_zone().id,
            })
