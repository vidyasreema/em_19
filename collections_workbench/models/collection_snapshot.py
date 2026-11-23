import logging
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_date

_logger = logging.getLogger(__name__)

SECTIONS = [
    ('active', 'Active list'),
    ('court', 'Court case'),
    ('blacklist', 'Blacklist'),
]

# Source documents of a snapshot (BR-1). Credit notes are not invoices:
# while unreconciled they show in the "Unreconciled" column instead.
INVOICE_TYPES = ('out_invoice', 'out_receipt')

# Payment mismatch check against the latest manual note (FR-31, VR-16, VR-17)
PAY_CHECKS = [
    ('ok', 'Payment confirmed'),
    ('unrec', 'New unreconciled payment'),
    ('missing', 'No trace of payment, check the bank'),
    ('nonote', 'Payment without a note'),
]
MISMATCHES = ('unrec', 'missing', 'nonote')


class CollectionSnapshot(models.Model):
    """Frozen list of open customer invoices for a period (BR-3, BR-4).

    Figures never change after generation. Never deleted; only the manager
    archives it (BR-6)."""
    _name = 'collection.snapshot'
    _description = 'Collection Snapshot'
    _inherit = ['mail.thread']
    _order = 'pull_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    period_type = fields.Selection(
        [('before_month', 'Before month'), ('range', 'From date to date')],
        string="Period", required=True, default='before_month', readonly=True)
    month_date = fields.Date(
        string="Before month", readonly=True,
        help="First day of the month: invoices dated before this day are included.")
    date_from = fields.Date(string="From", readonly=True)
    date_to = fields.Date(string="To", readonly=True)
    pull_date = fields.Datetime(string="Pulled on", readonly=True)
    generated_by = fields.Many2one('res.users', readonly=True, default=lambda self: self.env.user)
    state = fields.Selection([
        ('generating', 'Generating'),
        ('active', 'Active'),
        ('archived', 'Archived'),
    ], default='generating', required=True, readonly=True, tracking=True, index=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True, readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id')

    line_ids = fields.One2many('collection.snapshot.line', 'snapshot_id', string="Customers")
    invoice_ids = fields.One2many('collection.snapshot.invoice', 'snapshot_id', string="Invoices")

    # Frozen totals, written once at generation
    total_due = fields.Monetary(readonly=True)
    customer_count = fields.Integer(readonly=True)
    invoice_count = fields.Integer(readonly=True)
    unreconciled_total = fields.Monetary(string="Unreconciled at pull", readonly=True)
    unreconciled_customer_count = fields.Integer(readonly=True)
    first_invoice_date = fields.Date(readonly=True)
    last_invoice_date = fields.Date(readonly=True)

    is_latest = fields.Boolean(compute='_compute_is_latest')

    _FROZEN_AFTER_GENERATION = {
        'period_type', 'month_date', 'date_from', 'date_to', 'pull_date', 'generated_by',
        'company_id', 'total_due', 'customer_count', 'invoice_count', 'unreconciled_total',
        'unreconciled_customer_count', 'first_invoice_date', 'last_invoice_date',
    }

    @api.depends('period_type', 'month_date', 'date_from', 'date_to')
    def _compute_name(self):
        for snap in self:
            if snap.period_type == 'before_month' and snap.month_date:
                snap.name = _("Before %s", snap.month_date.strftime('%B %Y'))
            elif snap.date_from and snap.date_to:
                snap.name = _("%(from)s – %(to)s",
                              **{'from': format_date(self.env, snap.date_from),
                                 'to': format_date(self.env, snap.date_to)})
            else:
                snap.name = _("New snapshot")

    def _compute_is_latest(self):
        latest = self._get_latest()
        for snap in self:
            snap.is_latest = snap == latest

    @api.model
    def _get_latest(self):
        return self.search([('state', '=', 'active'), ('company_id', '=', self.env.company.id)],
                           order='pull_date desc, id desc', limit=1)

    # ------------------------------------------------------------------
    # Protection (BR-4, BR-6)
    # ------------------------------------------------------------------
    def write(self, vals):
        frozen = self._FROZEN_AFTER_GENERATION & set(vals)
        if frozen and any(s.state != 'generating' for s in self):
            raise UserError(_("A snapshot is frozen: its figures cannot change after generation."))
        return super().write(vals)

    def unlink(self):
        # Only a snapshot that never finished (no customers yet) can be removed
        if any(s.state != 'generating' or s.line_ids for s in self):
            raise UserError(_("A snapshot is never deleted. The manager can archive it."))
        if not self.env.user.has_group('collections_workbench.group_collection_manager'):
            raise AccessError(_("Only the manager can delete an unfinished snapshot."))
        return super().unlink()

    def action_generate_now(self):
        """Build a snapshot that is still waiting, right now (when the
        background job is switched off or failed)."""
        if not self.env.user.has_group('collections_workbench.group_collection_accountant'):
            raise AccessError(_("Only the accountant or the manager can generate a snapshot."))
        for snap in self.filtered(lambda s: s.state == 'generating'):
            snap.sudo()._generate()
        return True

    def action_delete_unfinished(self):
        if not self.env.user.has_group('collections_workbench.group_collection_manager'):
            raise AccessError(_("Only the manager can delete an unfinished snapshot."))
        self.sudo().unlink()  # accountants and managers have no delete right on snapshots
        return {'type': 'ir.actions.act_window_close'}

    # ------------------------------------------------------------------
    # Generation (FR-1)
    # ------------------------------------------------------------------
    def _invoice_domain(self):
        self.ensure_one()
        domain = [
            ('move_type', 'in', INVOICE_TYPES),
            ('state', '=', 'posted'),
            ('amount_residual', '>', 0),
            ('company_id', '=', self.company_id.id),
        ]
        if self.period_type == 'before_month':
            domain.append(('invoice_date', '<', self.month_date))
        else:
            domain += [('invoice_date', '>=', self.date_from), ('invoice_date', '<=', self.date_to)]
        return domain

    @api.model
    def _cron_generate_pending(self):
        for snap in self.search([('state', '=', 'generating')], order='id'):
            try:
                with self.env.cr.savepoint():
                    snap._generate()
            except Exception:
                _logger.exception("Collection snapshot %s failed to generate", snap.id)
                snap.message_post(
                    body=_("Generation failed. Please contact the administrator."),
                    partner_ids=snap.generated_by.partner_id.ids)

    def _generate(self):
        """Pull open invoices and freeze them. Runs in the background."""
        self.ensure_one()
        if self.state != 'generating':
            return
        Partner = self.env['res.partner']
        moves = self.env['account.move'].search(self._invoice_domain(), order='invoice_date, name')
        by_partner = defaultdict(lambda: self.env['account.move'])
        for move in moves:
            by_partner[move.partner_id] |= move

        company = self.company_id
        court_tags = company.collection_court_tag_ids
        black_tags = company.collection_blacklist_tag_ids
        unrec = Partner.browse([p.id for p in by_partner])._collection_unreconciled_by_partner()

        line_vals = []
        for partner, invoices in by_partner.items():
            tags = partner.category_id
            section = ('blacklist' if tags & black_tags
                       else 'court' if tags & court_tags
                       else 'active')
            line_vals.append({
                'snapshot_id': self.id,
                'partner_id': partner.id,
                'commercial_partner_id': partner.commercial_partner_id.id,
                'salesman_id': partner.sales_man.id,
                'assignee_at_pull_id': (partner.collection_assignee_id or partner.sales_man).id,
                'tag_ids': [(6, 0, tags.ids)],
                'section': section,
                'total_due': sum(invoices.mapped('amount_residual_signed')),
                'unreconciled_at_pull': unrec.get(partner.id, 0.0),
                'oldest_invoice_date': min(invoices.mapped('invoice_date')),
                'invoice_line_ids': [(0, 0, {
                    'snapshot_id': self.id,
                    'move_id': inv.id,
                    'invoice_date': inv.invoice_date,
                    'period_key': inv.invoice_date.strftime('%Y-%m'),
                    'amount_due_at_pull': inv.amount_residual_signed,
                }) for inv in invoices],
            })
        lines = self.env['collection.snapshot.line'].create(line_vals)

        # Customers without an assignee yet get the salesperson (BR-21)
        for partner in by_partner:
            if not partner.collection_assignee_id and partner.sales_man:
                partner.collection_assignee_id = partner.sales_man

        flagged = lines.filtered(lambda l: l.unreconciled_at_pull > 0.005)
        self.write({
            'state': 'active',
            'pull_date': fields.Datetime.now(),
            'total_due': sum(lines.mapped('total_due')),
            'customer_count': len(lines),
            'invoice_count': len(moves),
            'unreconciled_total': sum(flagged.mapped('unreconciled_at_pull')),
            'unreconciled_customer_count': len(flagged),
            'first_invoice_date': moves[:1].invoice_date,
            'last_invoice_date': moves[-1:].invoice_date,
        })
        # Statuses for the new list now, not at the next nightly run: every
        # customer is eligible for Claim from day one (BR-12, FR-20).
        self.env['res.partner'].browse(lines.partner_id.ids)._cron_collection_statuses()
        self.message_post(
            body=_("Snapshot ready: %(customers)s customers, %(invoices)s invoices.",
                   customers=len(lines), invoices=len(moves)),
            partner_ids=self.generated_by.partner_id.ids,
            subtype_xmlid='mail.mt_comment',
        )
        return True

    # ------------------------------------------------------------------
    # Archive (FR-3)
    # ------------------------------------------------------------------
    def action_archive_snapshot(self):
        if not self.env.user.has_group('collections_workbench.group_collection_manager'):
            raise AccessError(_("Only the manager can archive a snapshot."))
        self.filtered(lambda s: s.state == 'active').write({'state': 'archived'})

    def action_unarchive_snapshot(self):
        if not self.env.user.has_group('collections_workbench.group_collection_manager'):
            raise AccessError(_("Only the manager can restore a snapshot."))
        self.filtered(lambda s: s.state == 'archived').write({'state': 'active'})

    # ------------------------------------------------------------------
    # Live comparison (FR-30)
    # ------------------------------------------------------------------
    def _live_summary(self):
        """Current figures for the same snapshot invoices. The snapshot
        itself is not touched (AC-19)."""
        self.ensure_one()
        agreement_tags = self.company_id.collection_agreement_tag_ids
        open_total = collected = agr_open = agr_collected = 0.0
        paid = partly = not_paid = changed = 0
        for line in self.line_ids:
            line_collected = line.live_collected
            open_total += line.total_due
            collected += line_collected
            if line.tag_ids & agreement_tags:
                agr_open += line.total_due
                agr_collected += line_collected
            if line.live_status == 'paid':
                paid += 1
            elif line.live_status == 'partly':
                partly += 1
            else:
                not_paid += 1
            changed += line.changed_invoice_count
        ex_open = open_total - agr_open
        return {
            'open': open_total,
            'balance': open_total - collected,
            'collected': collected,
            'rate': collected / open_total if open_total else 0.0,
            'rate_ex_agreements': (collected - agr_collected) / ex_open if ex_open else 0.0,
            'paid': paid,
            'partly': partly,
            'not_paid': not_paid,
            'changed_invoices': changed,
            'unreconciled_now': sum(self.line_ids.mapped('unreconciled_now')),
            'mismatches': len(self.line_ids.filtered(lambda l: l.pay_check in MISMATCHES)),
        }


class CollectionSnapshotLine(models.Model):
    """One customer in a snapshot. Holds the internal discussion
    (Chatter + activities), which starts empty with each snapshot (BR-4)."""
    _name = 'collection.snapshot.line'
    _description = 'Collection Snapshot Line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'snapshot_id, section, oldest_invoice_date, total_due desc, id'
    _rec_name = 'partner_id'
    _mail_post_access = 'read'

    snapshot_id = fields.Many2one('collection.snapshot', required=True, ondelete='cascade',
                                  index=True, readonly=True)
    snapshot_state = fields.Selection(related='snapshot_id.state')
    company_id = fields.Many2one(related='snapshot_id.company_id', store=True)
    currency_id = fields.Many2one(related='snapshot_id.currency_id')
    partner_id = fields.Many2one('res.partner', string="Customer", required=True, index=True,
                                 readonly=True)
    commercial_partner_id = fields.Many2one('res.partner', readonly=True, index=True)

    # Frozen at pull
    salesman_id = fields.Many2one('hr.employee', string="Salesperson", readonly=True)
    assignee_at_pull_id = fields.Many2one('hr.employee', string="Assigned at pull", readonly=True)
    tag_ids = fields.Many2many('res.partner.category', string="Tags at pull", readonly=True)
    section = fields.Selection(SECTIONS, required=True, default='active', readonly=True)
    total_due = fields.Monetary(string="Total due", readonly=True)
    unreconciled_at_pull = fields.Monetary(readonly=True)
    oldest_invoice_date = fields.Date(readonly=True)
    invoice_line_ids = fields.One2many('collection.snapshot.invoice', 'line_id', string="Invoices")

    # Live, from the customer card (BR-2)
    assignee_id = fields.Many2one(
        related='partner_id.collection_assignee_id', readonly=False, string="Assigned to")
    assignee_user_id = fields.Many2one(
        'res.users', compute='_compute_assignee_user', search='_search_assignee_user')
    pipeline_id = fields.Many2one(related='partner_id.collection_pipeline_id')
    stage_id = fields.Many2one(related='partner_id.collection_stage_id')
    credit_limit = fields.Float(related='partner_id.credit_limit')
    customer_replied = fields.Boolean(string="Customer replied", copy=False)

    # Live comparison (FR-30) and checks (FR-29)
    unreconciled_now = fields.Monetary(compute='_compute_live', search='_search_unreconciled_now', string="Unreconciled")
    soa_balance = fields.Monetary(compute='_compute_live', search='_search_soa_balance', string="SOA balance")
    live_balance = fields.Monetary(compute='_compute_live', search='_search_live_balance', string="Updated balance")
    live_collected = fields.Monetary(compute='_compute_live', search='_search_live_collected', string="Collected")
    live_status = fields.Selection(
        [('paid', 'Paid'), ('partly', 'Partly paid'), ('none', 'Not paid')],
        compute='_compute_live', search='_search_live_status', string="Status")
    changed_invoice_count = fields.Integer(compute='_compute_live')
    latest_note_id = fields.Many2one('collection.note', compute='_compute_latest_note')
    pay_check = fields.Selection(PAY_CHECKS, string="Payment check", compute='_compute_pay_check',
                                 search='_search_pay_check')
    awaiting_approval = fields.Boolean(related='partner_id.collection_awaiting_approval',
                                       string="Awaiting approval")
    next_action = fields.Char(related='partner_id.collection_next_action', string="Suggested")
    due_to_send = fields.Boolean(related='partner_id.collection_due_to_send')

    _FROZEN = {'snapshot_id', 'partner_id', 'commercial_partner_id', 'salesman_id',
               'assignee_at_pull_id', 'tag_ids', 'section', 'total_due', 'unreconciled_at_pull',
               'oldest_invoice_date'}

    def write(self, vals):
        if self._FROZEN & set(vals) and any(l.snapshot_id.state != 'generating' for l in self):
            raise UserError(_("A snapshot is frozen: its figures cannot change after generation."))
        return super().write(vals)

    @api.depends('assignee_id')
    def _compute_assignee_user(self):
        for line in self:
            line.assignee_user_id = line.assignee_id.user_id

    def _search_assignee_user(self, operator, value):
        return [('partner_id.collection_assignee_id.user_id', operator, value)]

    def _compute_live(self):
        unrec = self.partner_id._collection_unreconciled_by_partner()
        for line in self:
            invs = line.invoice_line_ids
            line.unreconciled_now = unrec.get(line.partner_id.id, 0.0)
            line.soa_balance = line.total_due - line.unreconciled_now
            line.live_collected = sum(invs.mapped('collected'))
            line.live_balance = line.total_due - line.live_collected
            line.changed_invoice_count = len(invs.filtered('changed_after_snapshot'))
            if line.live_collected >= line.total_due - 0.005:
                line.live_status = 'paid'
            elif line.live_collected > 0.005:
                line.live_status = 'partly'
            else:
                line.live_status = 'none'

    def _compute_latest_note(self):
        Note = self.env['collection.note']
        for line in self:
            line.latest_note_id = Note.search(
                [('partner_id', '=', line.partner_id.id)], order='create_date desc, id desc', limit=1)

    def _compute_pay_check(self):
        """Batched: three queries for any number of lines (Appendix E)."""
        today = fields.Date.context_today(self)
        partners = self.partner_id
        notes_by = defaultdict(list)
        for note in self.env['collection.note'].search(
                [('partner_id', 'in', partners.ids), ('is_system', '=', False)], order='create_date, id'):
            notes_by[note.partner_id.id].append(note)
        AML = self.env['account.move.line'].sudo()  # collectors have no Accounting rights
        base = partners._collection_receivable_domain() if partners else [('id', '=', 0)]
        pays_by = defaultdict(list)
        for aml in AML.search_fetch(base + [
                ('balance', '<', 0), ('move_id.move_type', '=', 'entry'), ('date', '<=', today),
                '|', ('move_id.origin_payment_id', '!=', False), ('move_id.statement_line_id', '!=', False)],
                ['partner_id', 'date', 'balance', 'amount_residual'], order='date, id'):
            pays_by[aml.partner_id.id].append(aml)
        unrec_by = defaultdict(list)
        for aml in AML.search_fetch(base + [('reconciled', '=', False), ('amount_residual', '<', 0)],
                                    ['partner_id', 'date']):
            unrec_by[aml.partner_id.id].append(aml.date)
        for line in self:
            commercial = line.partner_id.commercial_partner_id.id
            line.pay_check = line._pay_check(
                today, notes_by[line.partner_id.id], pays_by[commercial], unrec_by[commercial])

    def _pay_check(self, today, notes, payments, unrec_dates):
        """Mirrors the simulation's payCheck()."""
        self.ensure_one()
        if not self.snapshot_id.pull_date:
            return False
        pull = self.snapshot_id.pull_date.date()
        last = notes[-1] if notes else None
        matched = [p for p in payments if abs(p.amount_residual) < abs(p.balance) - 0.005]
        if last and last.category_id.is_paid_claim and last.date >= pull:
            near = fields.Date.subtract(last.date, days=7)
            if self.live_collected > 0.005 or any(p.date >= near for p in matched):
                return 'ok'
            return 'unrec' if any(d >= pull for d in unrec_dates) else 'missing'
        if self.live_collected > 0.005:
            since = [p for p in payments if p.date >= pull]
            if not since:
                return False
            last_pay = since[-1]
            near = fields.Date.subtract(last_pay.date, days=7)
            if any(n.category_id.is_paid_claim and n.date >= near for n in notes):
                return False
            if last and (last.category_id.requires_date or last.category_id.closes_deadline) \
                    and last.date <= last_pay.date:
                return False
            return 'nonote'
        return False

    def _search_pay_check(self, operator, value):
        lines = self.search([('snapshot_id.state', '=', 'active')])
        if operator in ('=', '!=') and value is False:
            wanted = lines.filtered(lambda l: bool(l.pay_check) == (operator == '!='))
        elif operator == '=':
            wanted = lines.filtered(lambda l: l.pay_check == value)
        elif operator == 'in':
            wanted = lines.filtered(lambda l: l.pay_check in value)
        else:
            raise UserError(_("Unsupported search on the payment check."))
        return [('id', 'in', wanted.ids)]

    def action_collection_followup(self):
        return self.partner_id.action_collection_followup()

    def _message_get_suggested_recipients(self, *args, **kwargs):
        # Internal discussion only: never suggest the customer (BR-23)
        return []


class CollectionSnapshotInvoice(models.Model):
    """One frozen invoice. Basis of the period columns and the live
    comparison (FR-4, FR-30)."""
    _name = 'collection.snapshot.invoice'
    _description = 'Collection Snapshot Invoice'
    _order = 'invoice_date, id'

    snapshot_id = fields.Many2one('collection.snapshot', required=True, ondelete='cascade', index=True)
    line_id = fields.Many2one('collection.snapshot.line', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='snapshot_id.currency_id')
    move_id = fields.Many2one('account.move', string="Invoice", required=True, ondelete='restrict',
                              index=True)
    invoice_date = fields.Date(required=True)
    period_key = fields.Char(string="Month", required=True, help="YYYY-MM of the invoice date")
    amount_due_at_pull = fields.Monetary(string="Due at pull", required=True)

    live_residual = fields.Monetary(compute='_compute_live', string="Due now")
    collected = fields.Monetary(compute='_compute_live')
    changed_after_snapshot = fields.Boolean(compute='_compute_live', string="Changed after snapshot")

    def _compute_live(self):
        # A credit note matched after the pull (reversal, refund) is not a
        # collection (Obada point 4). Credit notes matched before the pull
        # are already in the frozen amount. One query for all invoices.
        refunded = set()
        by_pull = defaultdict(lambda: self.env['account.move'])
        for inv in self:
            if inv.snapshot_id.pull_date:
                by_pull[inv.snapshot_id.pull_date] |= inv.move_id
        for pull, moves in by_pull.items():
            partials = self.env['account.partial.reconcile'].sudo().search_fetch([
                ('debit_move_id.move_id', 'in', moves.ids),
                ('create_date', '>=', pull),
                ('credit_move_id.move_id.move_type', '=', 'out_refund'),
            ], ['debit_move_id'])
            refunded.update((pull, p.debit_move_id.move_id.id) for p in partials)
        for inv in self:
            move = inv.move_id.sudo()  # collectors have no Accounting rights
            # Reset to draft / cancelled after the pull (BR-7)
            changed = move.state != 'posted' or (inv.snapshot_id.pull_date, move.id) in refunded
            inv.changed_after_snapshot = changed
            if changed:
                inv.live_residual = inv.amount_due_at_pull
                inv.collected = 0.0
            else:
                inv.live_residual = move.amount_residual_signed
                inv.collected = max(0.0, inv.amount_due_at_pull - move.amount_residual_signed)
