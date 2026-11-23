import logging
from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_amount, format_date
from odoo.tools.mail import email_normalize_all
from .search_tools import bool_search_positive

_logger = logging.getLogger(__name__)

# Fields only the follow-up flow may write (BR-15: every move goes through
# the same rules and is logged with the channel and the user).
FOLLOWUP_FIELDS = {'collection_pipeline_id', 'collection_stage_id'}

PATTERNS = [
    ('none', 'No promises'),
    ('reliable', 'Reliable'),
    ('once', 'Late once'),
    ('repeat', 'Repeat'),
    ('chronic', 'Chronic'),
    ('unreach', 'Unreachable'),
]

DEADLINES = [
    ('none', 'No deadline'),
    ('open', 'Open'),
    ('soon', 'Upcoming'),
    ('today', 'Today'),
    ('late', 'Overdue'),
    ('late_us', 'Late on us'),
    ('closed', 'Closed'),
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # --- Assignment and pipeline (BR-2, BR-17, BR-21) ---------------------
    collection_assignee_id = fields.Many2one(
        'hr.employee', string="Collections assignee", tracking=True,
        help="Default: the Sales man on this card.")
    collection_pipeline_id = fields.Many2one(
        'collection.pipeline', string="Follow-up pipeline", tracking=True, index=True,
        ondelete='restrict')
    collection_stage_id = fields.Many2one(
        'collection.stage', string="Follow-up stage", tracking=True, index=True,
        domain="[('pipeline_id', '=', collection_pipeline_id)]", ondelete='restrict',
        group_expand='_read_group_collection_stage_ids')
    collection_stage_date = fields.Date(string="In stage since", tracking=True)
    collection_prev_stage_id = fields.Many2one(
        'collection.stage', string="Stage before partial payment", ondelete='set null')
    collection_cycle_start = fields.Date(string="Follow-up cycle started")
    collection_had_partial = fields.Boolean(string="Partial payment in this cycle")
    collection_max_stage_id = fields.Many2one(
        'collection.stage', string="Highest stage in this cycle", ondelete='set null')

    collection_note_ids = fields.One2many('collection.note', 'partner_id', string="Collection notes")
    collection_cycle_ids = fields.One2many('collection.cycle', 'partner_id', string="Closed cycles")
    collection_approval_ids = fields.One2many('collection.approval', 'partner_id', string="Approvals")

    # --- Daily statuses, recomputed by cron and after each note (Appendix E)
    collection_pattern = fields.Selection(PATTERNS, string="Behaviour pattern", default='none')
    collection_deadline_state = fields.Selection(DEADLINES, string="Deadline", default='none')
    collection_deadline_date = fields.Date(string="Deadline date")
    collection_next_stage_id = fields.Many2one(
        'collection.stage', string="Suggested stage", ondelete='set null')
    collection_due_to_send = fields.Boolean(string="Due to send")
    collection_suggest_blacklist = fields.Boolean(string="Blacklist suggested")
    collection_suggest_close = fields.Boolean(
        string="Close suggested", help="Paid in full while in Payment Agreements or Legal Cases (VR-14).")
    collection_next_action = fields.Char(string="Suggested next step")
    collection_remain_sent = fields.Boolean(string="Remaining balance request sent")
    collection_thanks_date = fields.Date(string="Last thank-you email", copy=False)
    collection_thanks_due = fields.Boolean(
        string="Thank-you due", help="A payment arrived after the last thank-you email.")
    collection_seen_payment_id = fields.Integer(
        string="Last payment line already handled", copy=False,
        help="Technical: payments after this one move the customer to Partial payment.")
    collection_snapshot_line_ids = fields.One2many(
        'collection.snapshot.line', 'partner_id', string="Snapshot lines")
    collection_awaiting_approval = fields.Boolean(
        compute='_compute_collection_awaiting_approval', search='_search_collection_awaiting_approval',
        string="Awaiting approval")

    # --- Live figures -------------------------------------------------------
    collection_open_balance = fields.Monetary(
        compute='_compute_collection_figures', string="Open balance",
        help="Remaining balance of all posted invoices to this customer (full period).")
    collection_unreconciled = fields.Monetary(
        compute='_compute_collection_figures', string="Unreconciled payments",
        help="Payments and credits received but not yet matched with invoices.")
    collection_last_payment_date = fields.Date(compute='_compute_collection_figures')
    collection_is_vip = fields.Boolean(compute='_compute_collection_flags')
    collection_is_blacklisted = fields.Boolean(compute='_compute_collection_flags')

    def _compute_collection_awaiting_approval(self):
        pending = self.env['collection.approval'].sudo()._read_group(
            [('partner_id', 'in', self.ids), ('state', '=', 'pending')], ['partner_id'])
        pending_ids = {partner.id for partner, in pending}
        for partner in self:
            partner.collection_awaiting_approval = partner.id in pending_ids

    def _search_collection_awaiting_approval(self, operator, value):
        pending = self.env['collection.approval'].sudo().search([('state', '=', 'pending')]).partner_id
        positive = bool_search_positive(operator, value)
        if positive is None:
            return []
        return [('id', 'in' if positive else 'not in', pending.ids)]

    @api.model
    def _read_group_collection_stage_ids(self, stages, domain):
        pipeline_id = self.env.context.get('default_collection_pipeline_id')
        if pipeline_id:
            return self.env['collection.stage'].search([('pipeline_id', '=', pipeline_id)])
        return stages

    # ------------------------------------------------------------------
    # Accounting helpers. Receivable lines always carry the commercial
    # partner, so balances and payments are read on it (Obada point 2).
    # ------------------------------------------------------------------
    def _collection_receivable_domain(self):
        return [
            ('partner_id', 'in', self.commercial_partner_id.ids),
            ('account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.env.company.id),
        ]

    def _collection_unreconciled_by_partner(self):
        """{partner id: unreconciled credit} — payments or credit notes not
        yet matched with invoices (basis of the "Unreconciled" flag)."""
        if not self:
            return {}
        # sudo: collectors without Accounting rights still see the flag (AC-28)
        data = self.env['account.move.line'].sudo()._read_group(
            self._collection_receivable_domain() + [
                ('reconciled', '=', False), ('amount_residual', '<', 0)],
            ['partner_id'], ['amount_residual:sum'])
        by_commercial = {partner.id: -amount for partner, amount in data}
        return {p.id: by_commercial.get(p.commercial_partner_id.id, 0.0) for p in self}

    def _collection_payment_lines(self, date_from=None, date_to=None):
        """Money received: receivable credits from payments / bank lines."""
        domain = self._collection_receivable_domain() + [
            ('balance', '<', 0),
            ('move_id.move_type', '=', 'entry'),
            '|', ('move_id.origin_payment_id', '!=', False),
                 ('move_id.statement_line_id', '!=', False),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return self.env['account.move.line'].sudo().search(domain, order='date, id')

    def _collection_paid_between(self, date_from, date_to):
        return -sum(self._collection_payment_lines(date_from, date_to).mapped('balance'))

    def _compute_collection_figures(self):
        unrec = self._collection_unreconciled_by_partner()
        balances = defaultdict(float)
        if self.ids:
            data = self.env['account.move'].sudo()._read_group(
                [('partner_id', 'in', self.ids), ('move_type', 'in', ('out_invoice', 'out_receipt')),
                 ('state', '=', 'posted'), ('amount_residual', '>', 0),
                 ('company_id', '=', self.env.company.id)],
                ['partner_id'], ['amount_residual_signed:sum'])
            balances.update({p.id: amount for p, amount in data})
        for partner in self:
            partner.collection_open_balance = balances.get(partner.id, 0.0)
            partner.collection_unreconciled = unrec.get(partner.id, 0.0)
            last = partner._collection_payment_lines()[-1:] if partner.id else False
            partner.collection_last_payment_date = last.date if last else False

    def _compute_collection_flags(self):
        company = self.env.company
        for partner in self:
            tags = partner.category_id
            partner.collection_is_vip = bool(tags & company.collection_vip_tag_ids)
            partner.collection_is_blacklisted = bool(tags & company.collection_blacklist_tag_ids)

    # ------------------------------------------------------------------
    # Behaviour pattern (FR-19) — mirrors the simulation's pattern()
    # ------------------------------------------------------------------
    def _collection_pattern(self, today=None):
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        company = self.env.company
        notes = self.collection_note_ids.filtered(lambda n: n.date <= today).sorted(
            lambda n: (n.create_date or fields.Datetime.now(), n.id))
        cut = None
        if company.collection_pattern_window > 0:
            cut = fields.Date.subtract(today, days=company.collection_pattern_window)
        promises = notes.filtered(lambda n: n.category_id.is_promise and (not cut or n.date > cut))

        kept = broken = 0
        broken_notes = []
        for note in promises:
            state = note._promise_state(today)
            if state == 'kept':
                kept += 1
            elif state == 'broken':
                broken += 1
                broken_notes.append(note)

        streak = 0
        for note in reversed(notes):
            if note.category_id.is_system:
                continue
            if note.category_id.is_no_answer:
                streak += 1
            else:
                break

        last_pay = self._collection_payment_lines(date_to=today)[-1:]
        open_broken = [n for n in broken_notes if not last_pay or n.promise_date > last_pay.date]
        open_days = (today - min(n.promise_date for n in open_broken)).days if open_broken else 0

        if streak >= company.collection_unreach_streak:
            return 'unreach'
        if broken >= company.collection_chronic_broken or (
                broken and open_days >= company.collection_chronic_days):
            return 'chronic'
        if broken >= company.collection_repeat_broken:
            return 'repeat'
        if broken == 1:
            return 'once'
        if kept:
            return 'reliable'
        return 'none'

    # ------------------------------------------------------------------
    # Deadline status (FR-18) — mirrors the simulation's deadlineOf()
    # ------------------------------------------------------------------
    def _collection_deadline(self, today=None):
        """(state, date)"""
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        notes = self.collection_note_ids.filtered(lambda n: n.date <= today).sorted(
            lambda n: (n.create_date or fields.Datetime.now(), n.id))
        dated = [n for n in notes if n.category_id.requires_date and n.promise_date]
        if not dated:
            return 'none', False
        note = dated[-1]
        later = notes.filtered(lambda n: n.create_date and note.create_date
                               and (n.create_date, n.id) > (note.create_date, note.id))
        if later.filtered(lambda n: n.category_id.closes_deadline):
            return 'closed', note.promise_date
        if self._collection_payment_lines(note.date, today):
            return 'closed', note.promise_date
        pdate = note.promise_date
        if pdate < today:
            return ('late_us' if note.category_id.late_on == 'us' else 'late'), pdate
        if pdate == today:
            return 'today', pdate
        if (pdate - today).days <= 7:
            return 'soon', pdate
        return 'open', pdate


    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    def write(self, vals):
        if FOLLOWUP_FIELDS & set(vals) and not self.env.context.get('collection_move'):
            raise UserError(_(
                'Use "Follow up" (or drag the card on the board) to move a customer: '
                'every move is logged with the channel and the user.'))
        if 'collection_assignee_id' not in vals:
            return super().write(vals)
        before = {p.id: p.collection_assignee_id for p in self}
        result = super().write(vals)
        for partner in self.filtered(lambda p: p.collection_assignee_id != before[p.id]):
            partner._collection_notify_assignment()
        return result

    def _collection_notify_assignment(self):
        """Assignment writes a line in the discussion and notifies the
        assignee in their Inbox (FR-34)."""
        self.ensure_one()
        employee = self.collection_assignee_id
        user = employee.user_id
        text = _("%(customer)s assigned to %(employee)s by %(user)s",
                 customer=self.display_name, employee=employee.name or _("nobody"), user=self.env.user.name)
        for line in self.sudo()._collection_active_lines():
            if user:
                line.message_subscribe(partner_ids=user.partner_id.ids)
            line.message_post(body=text, partner_ids=user.partner_id.ids if user else [],
                              subtype_xmlid='mail.mt_comment', message_type='notification')

    def _collection_check_user(self):
        if not self.env.user.has_group('collections_workbench.group_collection_user'):
            raise AccessError(_("Only Collections users can follow up customers."))

    def _collection_write(self, vals):
        """Write follow-up fields (as the system, logged by the caller)."""
        return self.sudo().with_context(collection_move=True).write(vals)

    def _collection_fresh(self):
        """Live figures are not stored: re-read them before any decision."""
        self.invalidate_recordset(['collection_open_balance', 'collection_unreconciled',
                                   'collection_last_payment_date'])
        return self

    def _collection_email_block_reason(self):
        """Why no email can go to this customer now (VR-7, VR-8), or False."""
        self.ensure_one()
        self._collection_fresh()
        if self.collection_unreconciled > 0.005:
            return _("Unreconciled payment, reconcile it first")
        if not self.email:
            return _("No email on the customer card")
        if not email_normalize_all(self.email):
            return _("The email on the customer card is not valid: %s", self.email)
        return False

    def _collection_needs_approval(self, stage):
        """VIP / High Profile customer and a stage that requires approval (VR-10)."""
        self.ensure_one()
        return bool(stage.requires_approval and self.collection_is_vip
                    and not self.env.context.get('collection_approved'))

    def _collection_active_lines(self):
        return self.collection_snapshot_line_ids.filtered(lambda l: l.snapshot_id.state == 'active')

    # ------------------------------------------------------------------
    # System notes and automatic tags (FR-26, BR-19, Appendix C)
    # ------------------------------------------------------------------
    def _collection_log(self, category_xmlid, text, channel=False, stage=False):
        self.ensure_one()
        return self.env['collection.note'].with_context(collection_skip_recompute=True).create({
            'partner_id': self.id,
            'category_id': self.env.ref('collections_workbench.' + category_xmlid).id,
            'body': text,
            'is_system': True,
            'channel': channel or False,
            'stage_id': stage.id if stage else False,
            'pipeline_id': stage.pipeline_id.id if stage else False,
        })

    def _collection_add_tags(self, tags, reason):
        """Add classification tags automatically, logging who and why (VR-15)."""
        self.ensure_one()
        new = tags - self.category_id
        if not new:
            return
        self.sudo().write({'category_id': [Command.link(tag.id) for tag in new]})
        text = _('Tag "%(tags)s" added automatically by %(user)s: %(reason)s',
                 tags=', '.join(new.mapped('name')), user=self.env.user.name, reason=reason)
        self._collection_log('note_cat_system', text)
        self.sudo().message_post(body=text, subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    # Emails (FR-25..27)
    # ------------------------------------------------------------------
    def _collection_template_values(self, deadline=False):
        """Values used by the collection email templates, as ctx keys."""
        self.ensure_one()
        company = self.env.company
        currency = company.currency_id
        today = fields.Date.context_today(self)
        balance = self.collection_open_balance
        last = self._collection_payment_lines()[-1:]
        remaining = ''
        if last and balance > 0.005:
            remaining = _(' A balance of %s remains outstanding.', format_amount(self.env, balance, currency))
        assignee = self.collection_assignee_id or getattr(self, 'sales_man', False)
        return {
            'cw_balance': format_amount(self.env, balance, currency),
            'cw_date': format_date(self.env, today),
            'cw_deadline': format_date(self.env, deadline) if deadline else '',
            'cw_paid': format_amount(self.env, -last.balance, currency) if last else '',
            'cw_paydate': format_date(self.env, last.date) if last else '',
            'cw_remaining': remaining,
            'cw_company': company.name,
            'cw_salesperson': assignee.name if assignee else '',
        }

    def _collection_render(self, template, deadline=False):
        """(subject, body) of `template` for this customer, in English (BR-26)."""
        self.ensure_one()
        if not template:
            return '', ''
        tmpl = template.sudo().with_context(lang='en_US', **self._collection_template_values(deadline))
        subject = tmpl._render_field('subject', self.ids)[self.id]
        body = tmpl._render_field('body_html', self.ids)[self.id]
        return subject, body

    def _collection_send_email(self, subject, body, attachments=None):
        """Send from the accountant's official address (FR-26). The email and
        any reply live on the customer card (BR-23)."""
        self.ensure_one()
        company = self.env.company
        sender = company.collection_sender_email or self.env.user.email_formatted
        message = self.sudo().message_post(
            body=body, subject=subject, partner_ids=self.ids, email_from=sender,
            attachments=attachments or [],
            message_type='comment', subtype_xmlid='mail.mt_comment',
            email_layout_xmlid='mail.mail_notification_light',
            # only the customer: staff following the contact get no copy of
            # every collection letter (the email stays on the card)
            notify_skip_followers=True)
        # whoever sends follows the snapshot line, to hear about replies (FR-28)
        lines = self._collection_active_lines()
        if lines:
            lines.sudo().message_subscribe(partner_ids=self.env.user.partner_id.ids)
            lines.sudo().customer_replied = False
        return message

    def _collection_send_event(self, label, subject, body):
        """Email outside the stages (statement, thanks, remaining balance,
        custom): the stage does not change (BR-24, AC-17)."""
        self.ensure_one()
        reason = self._collection_email_block_reason()
        if reason:
            raise UserError(_("%(customer)s: %(reason)s.", customer=self.display_name, reason=reason))
        attachments = []
        if label == 'soa':
            # the neutral statement email carries the PDF statement (BR-24)
            report = self.env.ref('collections_workbench.action_report_statement').sudo()
            pdf, _fmt = report.with_context(lang='en_US')._render_qweb_pdf(
                report.report_name, self.commercial_partner_id.ids, data={'mode': 'statement'})
            attachments = [(_("Statement - %s.pdf", self.commercial_partner_id.name), pdf)]
        self._collection_send_email(subject, body, attachments=attachments)
        if label == 'thanks':
            self._collection_write({'collection_thanks_date': fields.Date.context_today(self)})
        if label == 'remain' and self.collection_stage_id.is_partial:
            self._collection_write({
                'collection_remain_sent': True,
                'collection_stage_date': fields.Date.context_today(self),
            })
        names = {
            'soa': _("Statement of account"),
            'thanks': _("Thank you for payment"),
            'remain': _("Remaining balance request"),
            'custom': _("Custom message"),
        }
        self._collection_log('note_cat_email_sent', _('Email "%(kind)s" sent: %(subject)s',
                                                      kind=names.get(label, label), subject=subject),
                             channel='email')
        self._collection_recompute_status()

    # ------------------------------------------------------------------
    # Stage moves (BR-14, BR-15, BR-17, FR-22)
    # ------------------------------------------------------------------
    def _collection_apply_stage(self, stage, channel='email', note=False, subject=False, body=False,
                                approval=False):
        """Move this customer to `stage` and apply the stage effects.

        channel 'email' sends the stage email; any other channel records the
        stage without email. Approval routing is done by the caller."""
        self.ensure_one()
        self._collection_check_user()
        if channel == 'email':
            reason = self._collection_email_block_reason()
            if reason:
                raise UserError(_("%(customer)s: %(reason)s.", customer=self.display_name, reason=reason))
        if self._collection_needs_approval(stage):
            raise UserError(_('"%(stage)s" needs approval for %(customer)s.',
                              stage=stage.name, customer=self.display_name))
        today = fields.Date.context_today(self)
        pipeline = stage.pipeline_id
        old_pipeline = self.collection_pipeline_id
        payments = self._collection_payment_lines()
        vals = {
            'collection_pipeline_id': pipeline.id,
            'collection_stage_id': stage.id,
            'collection_stage_date': today,
            'collection_remain_sent': False,
            'collection_seen_payment_id': max(payments.ids) if payments else 0,
        }
        if not self.collection_cycle_start:
            vals['collection_cycle_start'] = today
        if pipeline.pipeline_type == 'collection' and not stage.is_partial:
            vals['collection_prev_stage_id'] = False
            top = self.collection_max_stage_id
            if not top or top.pipeline_id != pipeline or stage.sequence > top.sequence:
                vals['collection_max_stage_id'] = stage.id

        if channel == 'email':
            self._collection_send_email(subject, body)
        self._collection_write(vals)

        approved = ''
        if approval:
            approved = _(" (%(how)s, recorded by %(user)s)",
                         how=dict(approval._fields['approved_as'].selection).get(approval.approved_as),
                         user=self.env.user.name)
        if channel == 'email':
            text = _('Stage "%(stage)s": email sent "%(subject)s"%(approved)s',
                     stage=stage.name, subject=subject, approved=approved)
            category = 'note_cat_email_sent'
        else:
            from .collection_note import CHANNELS
            text = _('Stage "%(stage)s" recorded without email: %(channel)s%(approved)s',
                     stage=stage.name, channel=dict(CHANNELS).get(channel, channel), approved=approved)
            category = 'note_cat_stage_recorded'
        if note:
            text = '%s. %s' % (text, note)
        self._collection_log(category, text, channel=channel, stage=stage)

        if pipeline != old_pipeline and pipeline.tag_id:
            self._collection_add_tags(pipeline.tag_id, _('entered "%s"', pipeline.name))
        if stage.sets_credit_limit:
            self._collection_set_credit_hold(stage)
        self._collection_recompute_status()
        return True

    def _collection_set_credit_hold(self, stage):
        """Credit sales hold: credit limit = current balance on the customer
        card, the same field POS checks (BR-14, VR-11)."""
        self.ensure_one()
        partner = self.commercial_partner_id.sudo()
        balance = partner.credit
        old = partner.credit_limit
        partner.write({'credit_limit': balance})
        currency = self.env.company.currency_id
        self._collection_log('note_cat_system', _(
            'Credit limit changed from %(old)s to %(new)s (stage "%(stage)s")',
            old=format_amount(self.env, old, currency), new=format_amount(self.env, balance, currency),
            stage=stage.name), stage=stage)

    def _collection_request_approval(self, stage, channel, note=False, subject=False, body=False,
                                     template=False):
        """VIP: nothing is sent; the request waits in the Approvals queue (BR-16)."""
        self.ensure_one()
        self._collection_check_user()
        request = self.env['collection.approval'].sudo().create({
            'partner_id': self.id,
            'pipeline_id': stage.pipeline_id.id,
            'stage_id': stage.id,
            'channel': channel,
            'template_id': template.id if template else False,
            'subject': subject or False,
            'body': body or False,
            'note': note or False,
            'requested_by': self.env.user.id,
        })
        self._collection_log('note_cat_system', _('Awaiting approval: stage "%s"', stage.name), stage=stage)
        return request

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_collection_followup(self, stage=None, pipeline=None, channel=None):
        self._collection_check_user()
        ctx = {'default_partner_ids': self.ids}
        if stage:
            ctx.update(default_pipeline_id=stage.pipeline_id.id, default_stage_id=stage.id)
        elif pipeline:
            ctx['default_pipeline_id'] = pipeline.id
        if channel:
            ctx.update(default_send_mode='record', default_channel=channel)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Follow up'),
            'res_model': 'collection.followup.wizard',
            'view_mode': 'form', 'views': [(False, 'form')],
            'target': 'new',
            'context': ctx,
        }

    def action_collection_move_blacklist(self):
        """Confirm the blacklist suggestion after the final notice (VR-13)."""
        pipeline = self.env['collection.pipeline'].search([('pipeline_type', '=', 'blacklist')], limit=1)
        if not pipeline.stage_ids:
            raise UserError(_("The Blacklist pipeline has no stage."))
        return self.action_collection_followup(stage=pipeline.stage_ids[:1], channel='other')

    def action_collection_close(self):
        """Management closes an agreement or legal case paid in full (VR-14)."""
        if not self.env.user.has_group('collections_workbench.group_collection_manager'):
            raise AccessError(_("Only the manager can close a follow-up."))
        today = fields.Date.context_today(self)
        for partner in self.filtered('collection_pipeline_id'):
            partner._collection_close_cycle(today, _("closed by %s", self.env.user.name))
        return True

    def collection_board_drop(self, stage_id):
        """Card dropped on a board column (FR-22, VR-12). Stages with an email,
        a VIP approval or another pipeline open the Follow up dialog: nothing
        moves before confirmation. Other stages move directly."""
        self.ensure_one()
        self._collection_check_user()
        stage = self.env['collection.stage'].browse(stage_id).exists()
        if not stage:
            raise UserError(_("A customer cannot be dragged out of the stages. Use Follow up instead."))
        if stage == self.collection_stage_id:
            return False
        if (stage.has_email or self._collection_needs_approval(stage)
                or (self.collection_pipeline_id and stage.pipeline_id != self.collection_pipeline_id)):
            return self.action_collection_followup(stage=stage)
        self._collection_apply_stage(stage, channel='other', note=_("Moved on the board"))
        return False

    # ------------------------------------------------------------------
    # Payments: partial payment and full payment (BR-13, BR-25, VR-14)
    # ------------------------------------------------------------------
    def _collection_close_cycle(self, today, reason=False):
        self.ensure_one()
        stage = self.collection_stage_id
        last = self._collection_payment_lines()[-1:]
        end = last.date if last and last.date >= (self.collection_cycle_start or last.date) else today
        start = self.collection_cycle_start or self.collection_stage_date or end
        top = self.collection_max_stage_id or self.collection_prev_stage_id or stage
        self.env['collection.cycle'].sudo().create({
            'partner_id': self.id,
            'date_start': min(start, end),
            'date_end': end,
            'max_stage_id': top.id if top else False,
            'had_partial': self.collection_had_partial or bool(stage.is_partial),
        })
        pipeline_name = self.collection_pipeline_id.name
        self._collection_write({
            'collection_pipeline_id': False,
            'collection_stage_id': False,
            'collection_stage_date': False,
            'collection_prev_stage_id': False,
            'collection_cycle_start': False,
            'collection_had_partial': False,
            'collection_max_stage_id': False,
            'collection_remain_sent': False,
            'collection_suggest_close': False,
        })
        self._collection_log('note_cat_system', _(
            'Cycle closed (%(why)s): %(pipeline)s, highest stage "%(top)s", %(days)s days',
            why=reason or _("paid in full"), pipeline=pipeline_name, top=top.name if top else '-',
            days=(end - min(start, end)).days))

    def _collection_sync_payments(self, today):
        """Full payment closes the collection cycle; a payment while in a
        collection stage pauses escalation in "Partial payment"."""
        self.ensure_one()
        pipeline = self.collection_pipeline_id
        stage = self.collection_stage_id
        if not stage or pipeline.pipeline_type != 'collection':
            return
        if self.collection_open_balance <= 0.005:
            self._collection_close_cycle(today)
            return
        company = self.env.company
        if not company.collection_partial_enabled:
            if stage.is_partial:
                self._collection_write({
                    'collection_stage_id': self.collection_prev_stage_id.id or False,
                    'collection_prev_stage_id': False,
                    'collection_remain_sent': False,
                })
            return
        partial = pipeline.stage_ids.filtered('is_partial')[:1]
        if not partial:
            return
        new = self._collection_payment_lines().filtered(lambda l: l.id > self.collection_seen_payment_id)
        if not new:
            return
        amount = -sum(new.mapped('balance'))
        vals = {
            'collection_stage_id': partial.id,
            'collection_stage_date': max(new.mapped('date')),
            'collection_had_partial': True,
            'collection_remain_sent': False,
            'collection_seen_payment_id': max(new.ids),
        }
        if not stage.is_partial:
            vals['collection_prev_stage_id'] = stage.id
        self._collection_write(vals)
        self._collection_log('note_cat_system', _(
            'Partial payment %(amount)s received: moved to stage "%(stage)s"',
            amount=format_amount(self.env, amount, company.currency_id), stage=partial.name), stage=partial)

    # ------------------------------------------------------------------
    # Hooks and daily statuses
    # ------------------------------------------------------------------
    def _collection_after_notes(self, notes):
        """Called after notes are created on these customers."""
        for note in notes.filtered(lambda n: n.category_id.is_blacklist_recommendation):
            note.partner_id._collection_on_blacklist_recommended(note)
        if not self.env.context.get('collection_skip_recompute'):
            self._collection_recompute_status()

    def _collection_on_blacklist_recommended(self, note):
        """A "Blacklist recommended" note adds the blacklist tag and moves the
        customer to the Blacklist pipeline (BR-19, AC-23)."""
        self.ensure_one()
        pipeline = self.env['collection.pipeline'].search([('pipeline_type', '=', 'blacklist')], limit=1)
        tags = self.env.company.collection_blacklist_tag_ids or pipeline.tag_id
        if tags:
            self._collection_add_tags(tags, _('"Blacklist recommended" note'))
        if pipeline.stage_ids and self.collection_pipeline_id != pipeline:
            self._collection_apply_stage(pipeline.stage_ids[:1], channel='other',
                                         note=_("Blacklist recommended by %s", note.user_id.name))

    def _collection_recompute_status(self, today=None):
        today = today or fields.Date.context_today(self)
        for partner in self:
            partner._collection_fresh()._collection_sync_payments(today)
            partner._collection_fresh()
            deadline, deadline_date = partner._collection_deadline(today)
            vals = {
                'collection_pattern': partner._collection_pattern(today),
                'collection_deadline_state': deadline,
                'collection_deadline_date': deadline_date,
            }
            vals.update(partner._collection_next_action_vals(today))
            # values are plain (ids for many2one): compare the same way
            current = {k: partner[k].id if partner._fields[k].type == 'many2one' else partner[k]
                       for k in vals}
            changed = {k: v for k, v in vals.items() if current[k] != v}
            if changed:
                partner.sudo().with_context(tracking_disable=True).write(changed)

    def _collection_next_action_vals(self, today):
        """Suggested next stage and "Due to send" (FR-20), blacklist (VR-13)
        and close (VR-14) suggestions. Mirrors the simulation's nextAction()."""
        self.ensure_one()
        vals = {
            'collection_next_stage_id': False,
            'collection_next_action': False,
            'collection_due_to_send': False,
            'collection_suggest_blacklist': False,
            'collection_suggest_close': False,
            'collection_thanks_due': self._collection_thanks_due(),
        }
        pipeline = self.collection_pipeline_id
        stage = self.collection_stage_id
        if self.collection_open_balance <= 0.005:
            if pipeline.pipeline_type in ('agreement', 'legal'):
                vals.update(collection_suggest_close=True, collection_next_action=_("Close: paid in full"))
            return vals
        if pipeline and pipeline.pipeline_type != 'collection':
            return vals
        ladder = self.env['collection.pipeline']._get_collection().stage_ids.filtered(
            lambda s: not s.is_partial).sorted(lambda s: (s.sequence, s.id))
        if not ladder:
            return vals
        if not stage:
            # every customer in the snapshot is eligible for the first stage (BR-12)
            if self._collection_active_lines():
                vals.update(collection_next_stage_id=ladder[0].id, collection_next_action=ladder[0].name,
                            collection_due_to_send=True)
            return vals
        days = (today - (self.collection_stage_date or today)).days
        if stage.is_partial:
            if self.collection_remain_sent:
                prev = self.collection_prev_stage_id
                idx = ladder.ids.index(prev.id) if prev.id in ladder.ids else -1
                nxt = ladder[min(idx + 1, len(ladder) - 1)]
                vals.update(collection_next_stage_id=nxt.id, collection_next_action=nxt.name)
            else:
                vals['collection_next_action'] = _("Remaining balance request")
            vals['collection_due_to_send'] = days >= self.env.company.collection_partial_wait
            return vals
        if stage.id not in ladder.ids:
            return vals
        idx = ladder.ids.index(stage.id)
        if idx == len(ladder) - 1:
            vals['collection_next_action'] = _("End of stages")
        else:
            nxt = ladder[idx + 1]
            vals.update(collection_next_stage_id=nxt.id, collection_next_action=nxt.name,
                        collection_due_to_send=days >= stage.wait_days)
        if stage.suggests_blacklist and days >= stage.wait_days and not self.collection_is_blacklisted:
            vals['collection_suggest_blacklist'] = True
        return vals

    def _collection_thanks_due(self):
        """A payment arrived after the last thank-you email (simulation thanksDue).
        Counted from the last thank-you, else the cycle start, else the
        active snapshot pull, so old payments do not count."""
        self.ensure_one()
        if self.collection_thanks_date:
            since = fields.Date.add(self.collection_thanks_date, days=1)
        else:
            since = self.collection_cycle_start
            if not since:
                pulls = self._collection_active_lines().snapshot_id.mapped('pull_date')
                since = min(pulls).date() if pulls else False
        if not since:
            return False
        return bool(self._collection_payment_lines(date_from=since))

    @api.model
    def _cron_collection_daily(self):
        """Daily: deadlines, due to send, pattern, partial / full payments (Appendix E)."""
        domain = ['|', '|', ('collection_note_ids', '!=', False),
                  ('collection_pipeline_id', '!=', False),
                  ('id', 'in', self.env['collection.snapshot.line'].search(
                      [('snapshot_id.state', '=', 'active')]).partner_id.ids)]
        self.search(domain)._cron_collection_statuses()

    def _cron_collection_statuses(self):
        for partner in self:
            try:
                with self.env.cr.savepoint():
                    partner._collection_recompute_status()
            except Exception:
                _logger.exception("Collections: status update failed for partner %s", partner.id)

    # ------------------------------------------------------------------
    # Customer replied (FR-28, AC-18)
    # ------------------------------------------------------------------
    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        if len(self) == 1 and message.message_type == 'email':
            author_users = message.author_id.user_ids
            if not author_users.filtered(lambda u: not u.share):
                self._collection_customer_replied(message)
        return message

    def _collection_customer_replied(self, message):
        lines = self.sudo()._collection_active_lines()
        if not lines:
            return
        lines.customer_replied = True
        for line in lines:
            line.message_post(
                body=_("The customer replied by email: %s", message.subject or self.display_name),
                subtype_xmlid='mail.mt_comment', message_type='notification')
