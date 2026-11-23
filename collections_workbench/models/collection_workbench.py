"""Server side of the Collections table (FR-5..FR-16, FR-29..FR-36).

The table itself is a custom OWL component bound to the line list view with
js_class="collection_workbench" (Appendix E). It reads everything it shows
through `workbench_data`, in a few batched queries, so it opens within two
seconds for 500 customers."""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_date

from .collection_snapshot import MISMATCHES, SECTIONS
from .search_tools import bool_search_positive

# Numeric live columns that can be filtered from their header (FR-10)
LIVE_NUMBERS = ('unreconciled_now', 'soa_balance', 'live_balance', 'live_collected')

OPERATORS = {
    '=': lambda a, b: a == b,
    '!=': lambda a, b: a != b,
    '>': lambda a, b: a > b,
    '>=': lambda a, b: a >= b,
    '<': lambda a, b: a < b,
    '<=': lambda a, b: a <= b,
}


class CollectionWorkbenchPref(models.Model):
    """Per-user table preferences: column widths, hidden columns, period
    grouping and collapsed sections (Appendix E, FR-6, FR-11, FR-12)."""
    _name = 'collection.workbench.pref'
    _description = 'Collections table preferences'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True,
                              default=lambda self: self.env.user)
    prefs = fields.Json()

    _user_unique = models.Constraint('UNIQUE(user_id)', 'One preference record per user.')

    @api.model
    def get_prefs(self):
        rec = self.sudo().search([('user_id', '=', self.env.uid)], limit=1)
        return rec.prefs or {}

    @api.model
    def set_prefs(self, prefs):
        rec = self.sudo().search([('user_id', '=', self.env.uid)], limit=1)
        if rec:
            rec.prefs = prefs
        else:
            self.sudo().create({'user_id': self.env.uid, 'prefs': prefs})
        return True


class CollectionSnapshotLine(models.Model):
    _inherit = 'collection.snapshot.line'

    latest_note_category_id = fields.Many2one(
        'collection.note.category', string="Latest note category",
        compute='_compute_latest_note_category', search='_search_latest_note_category')
    is_agreement = fields.Boolean(
        string="Agreement", compute='_compute_is_agreement', search='_search_is_agreement')
    deadline_state = fields.Selection(related='partner_id.collection_deadline_state', string="Deadline")
    live_section = fields.Selection(
        SECTIONS, string="List", compute='_compute_live_section', search='_search_live_section',
        help="Active list, Court case or Blacklist from the customer's current tags (BR-20, AC-22).")
    pattern = fields.Selection(related='partner_id.collection_pattern', string="Pattern")
    suggest_blacklist = fields.Boolean(related='partner_id.collection_suggest_blacklist')
    suggest_close = fields.Boolean(related='partner_id.collection_suggest_close')
    thanks_due = fields.Boolean(related='partner_id.collection_thanks_due')
    credit_state = fields.Selection(
        [('hold', 'Credit on hold'), ('available', 'Credit available'), ('none', 'No credit limit')],
        string="Credit", compute='_compute_credit_state', search='_search_credit_state',
        help="On hold: the open balance has reached the credit limit.")
    stale = fields.Boolean(
        string="No follow-up for 14+ days", compute='_compute_stale', search='_search_stale',
        help="No note, call or email logged for this customer in the last 14 days.")

    # ------------------------------------------------------------------
    # Credit state and stale follow-up (quick filters)
    # ------------------------------------------------------------------
    @api.model
    def _credit_state_of(self, partners):
        result = {}
        for partner in partners:
            commercial = partner.commercial_partner_id.sudo()  # credit needs Accounting rights
            limit = commercial.credit_limit
            if limit <= 0:
                result[partner.id] = 'none'
            else:
                result[partner.id] = 'hold' if commercial.credit >= limit - 0.005 else 'available'
        return result

    def _compute_credit_state(self):
        states = self._credit_state_of(self.partner_id)
        for line in self:
            line.credit_state = states.get(line.partner_id.id, 'none')

    def _search_credit_state(self, operator, value):
        if operator not in ('=', 'in', '!=', 'not in'):
            raise UserError(_("Unsupported filter on the credit."))
        values = {value} if isinstance(value, str) else set(value)
        lines = self.search([('snapshot_id.state', '!=', 'generating')])
        states = self._credit_state_of(lines.partner_id)
        keep = (lambda st: st in values) if operator in ('=', 'in') else (lambda st: st not in values)
        return [('id', 'in', lines.filtered(lambda l: keep(states.get(l.partner_id.id, 'none'))).ids)]

    @api.model
    def _stale_partner_ids(self, partners):
        limit = fields.Date.subtract(fields.Date.context_today(self), days=14)
        recent = self.env['collection.note']._read_group(
            [('partner_id', 'in', partners.ids), ('date', '>', limit)], ['partner_id'])
        fresh = {partner.id for partner, in recent}
        return set(partners.ids) - fresh

    def _compute_stale(self):
        stale = self._stale_partner_ids(self.partner_id)
        for line in self:
            line.stale = line.partner_id.id in stale

    def _search_stale(self, operator, value):
        lines = self.search([('snapshot_id.state', '!=', 'generating')])
        stale = self._stale_partner_ids(lines.partner_id)
        positive = bool_search_positive(operator, value)
        if positive is None:
            return []
        return [('id', 'in', lines.filtered(lambda l: (l.partner_id.id in stale) == positive).ids)]

    # ------------------------------------------------------------------
    # Searchable live figures (header filters, FR-10)
    # ------------------------------------------------------------------
    def _search_live_number(self, field, operator, value):
        if operator not in OPERATORS:
            raise UserError(_("Unsupported filter on %s.", self._fields[field].string))
        lines = self.search([('snapshot_id.state', '!=', 'generating')])
        return [('id', 'in', lines.filtered(
            lambda l: OPERATORS[operator](l[field], value or 0.0)).ids)]

    def _search_unreconciled_now(self, operator, value):
        return self._search_live_number('unreconciled_now', operator, value)

    def _search_soa_balance(self, operator, value):
        return self._search_live_number('soa_balance', operator, value)

    def _search_live_balance(self, operator, value):
        return self._search_live_number('live_balance', operator, value)

    def _search_live_collected(self, operator, value):
        return self._search_live_number('live_collected', operator, value)

    def _compute_latest_note_category(self):
        for line in self:
            line.latest_note_category_id = line.latest_note_id.category_id

    def _search_latest_note_category(self, operator, value):
        if operator not in ('in', '='):
            raise UserError(_("Unsupported filter on the latest note."))
        ids = [value] if isinstance(value, int) else list(value)
        lines = self.search([('snapshot_id.state', '!=', 'generating')])
        latest, _counts = self._latest_notes_by_partner(lines.partner_id)
        return [('id', 'in', lines.filtered(
            lambda l: latest.get(l.partner_id.id) and latest[l.partner_id.id].category_id.id in ids).ids)]

    def _compute_live_section(self):
        company = self.env.company
        black, court = company.collection_blacklist_tag_ids, company.collection_court_tag_ids
        for line in self:
            tags = line.partner_id.category_id
            line.live_section = 'blacklist' if tags & black else 'court' if tags & court else 'active'

    def _search_live_section(self, operator, value):
        if operator not in ('=', 'in'):
            raise UserError(_("Unsupported filter on the list."))
        values = [value] if isinstance(value, str) else list(value)
        company = self.env.company
        black, court = company.collection_blacklist_tag_ids.ids, company.collection_court_tag_ids.ids
        domains = {
            'blacklist': [('partner_id.category_id', 'in', black)],
            'court': ['&', ('partner_id.category_id', 'in', court), ('partner_id.category_id', 'not in', black)],
            'active': ['&', ('partner_id.category_id', 'not in', court), ('partner_id.category_id', 'not in', black)],
        }
        parts = [domains[v] for v in values if v in domains]
        if not parts:
            return [('id', '=', 0)]
        return ['|'] * (len(parts) - 1) + [leaf for part in parts for leaf in part]

    def _compute_is_agreement(self):
        tags = self.env.company.collection_agreement_tag_ids
        for line in self:
            line.is_agreement = bool(line.partner_id.category_id & tags)

    def _search_is_agreement(self, operator, value):
        tags = self.env.company.collection_agreement_tag_ids
        positive = bool_search_positive(operator, value)
        if positive is None:
            return []
        return [('partner_id.category_id', 'in' if positive else 'not in', tags.ids)]

    # ------------------------------------------------------------------
    # Internal discussion never reaches the customer (BR-23, VR-18)
    # ------------------------------------------------------------------
    def message_post(self, **kwargs):
        if kwargs.get('partner_ids'):
            partners = self.env['res.partner'].browse(kwargs['partner_ids'])
            kwargs['partner_ids'] = partners.filtered(
                lambda p: p.user_ids.filtered(lambda u: not u.share)).ids
        return super().message_post(**kwargs)

    def _message_add_suggested_recipients(self, *args, **kwargs):
        return []

    # ------------------------------------------------------------------
    # Batched helpers
    # ------------------------------------------------------------------
    @api.model
    def _latest_notes_by_partner(self, partners, limit_per_partner=1):
        """{partner id: latest note} in one query."""
        notes = self.env['collection.note'].search(
            [('partner_id', 'in', partners.ids)], order='create_date desc, id desc')
        result = {}
        counts = defaultdict(int)
        for note in notes:
            counts[note.partner_id.id] += 1
            result.setdefault(note.partner_id.id, note)
        return result, counts

    def _compute_latest_note(self):
        latest, _counts = self._latest_notes_by_partner(self.partner_id)
        for line in self:
            line.latest_note_id = latest.get(line.partner_id.id, False)

    @api.model
    def _workbench_periods(self, snapshot, mode, breaks=None):
        """Period columns (FR-6). Default: each previous year one column,
        the current year merged, and the last two months separate (AC-6)."""
        keys = sorted(set(snapshot.invoice_ids.mapped('period_key')))
        if not keys:
            return []
        if mode == 'custom' and breaks:
            return self._custom_periods(keys, breaks)
        if mode == 'month':
            return [{'key': k, 'label': self._month_label(k), 'months': [k], 'kind': 'month'} for k in keys]
        years = sorted({k[:4] for k in keys})
        if mode == 'year':
            return [{'key': y, 'label': y, 'months': [k for k in keys if k[:4] == y], 'kind': 'year'}
                    for y in years]
        # The last month of the snapshot period, even without invoices (AC-6)
        if snapshot.period_type == 'before_month' and snapshot.month_date:
            end = fields.Date.subtract(snapshot.month_date, months=1)
        else:
            end = snapshot.date_to or fields.Date.from_string(keys[-1] + '-01')
        end_key = end.strftime('%Y-%m')
        prev_key = fields.Date.subtract(end.replace(day=1), months=1).strftime('%Y-%m')
        current_year = end_key[:4]
        last_two = [k for k in (prev_key, end_key) if k[:4] == current_year]
        periods = [{'key': y, 'label': y, 'months': [k for k in keys if k[:4] == y], 'kind': 'year'}
                   for y in years if y < current_year]
        first_of_year = current_year + '-01'
        if last_two and last_two[0] > first_of_year:
            merged_end = fields.Date.subtract(fields.Date.from_string(last_two[0] + '-01'), months=1)
            merged = [k for k in keys if first_of_year <= k <= merged_end.strftime('%Y-%m')]
            label = 'Jan %s' % current_year if merged_end.month == 1 else '%s–%s' % (
                'Jan', merged_end.strftime('%b %Y'))
            periods.append({'key': 'merged', 'label': label, 'months': merged, 'kind': 'merged'})
        periods += [{'key': k, 'label': self._month_label(k), 'months': [k], 'kind': 'month'}
                    for k in last_two]
        # invoices after the period end (date ranges) still get a column
        extra = [k for k in keys if k > end_key]
        periods += [{'key': k, 'label': self._month_label(k), 'months': [k], 'kind': 'month'} for k in extra]
        return periods

    @api.model
    def _custom_periods(self, keys, breaks):
        """User-defined grouping (FR-6): a new column starts at each month
        in `breaks`; the months in between are merged."""
        groups = []
        for key in keys:
            if not groups or key in breaks:
                groups.append([key])
            else:
                groups[-1].append(key)
        periods = []
        for i, months in enumerate(groups):
            first = fields.Date.from_string(months[0] + '-01')
            last = fields.Date.from_string(months[-1] + '-01')
            if len(months) == 1:
                label = first.strftime('%b %Y')
            elif first.year == last.year:
                label = '%s–%s' % (first.strftime('%b'), last.strftime('%b %Y'))
            else:
                label = '%s–%s' % (first.strftime('%b %Y'), last.strftime('%b %Y'))
            periods.append({'key': 'c%s' % i, 'label': label, 'months': months,
                            'kind': 'month' if len(months) == 1 else 'merged'})
        return periods

    @api.model
    def _month_label(self, key):
        return fields.Date.from_string(key + '-01').strftime('%b %Y')

    # ------------------------------------------------------------------
    # RPC: the table
    # ------------------------------------------------------------------
    @api.model
    def workbench_snapshots(self):
        Snapshot = self.env['collection.snapshot']
        latest = Snapshot._get_latest()
        snaps = Snapshot.search([('state', '!=', 'generating'), ('company_id', '=', self.env.company.id)])
        return {
            'latest_id': latest.id,
            'snapshots': [{'id': s.id, 'name': s.name, 'state': s.state,
                           'pull_date': fields.Datetime.to_string(s.pull_date) if s.pull_date else False}
                          for s in snaps],
            'generating': bool(Snapshot.search_count([('state', '=', 'generating')])),
            'is_accountant': self.env.user.has_group('collections_workbench.group_collection_accountant'),
            'is_manager': self.env.user.has_group('collections_workbench.group_collection_manager'),
        }

    @api.model
    def workbench_data(self, snapshot_id, domain=None, period_mode='default', period_breaks=None):
        snapshot = self.env['collection.snapshot'].browse(snapshot_id).exists()
        if not snapshot:
            return {'snapshot': False, 'rows': [], 'periods': []}
        lines = self.search([('snapshot_id', '=', snapshot.id)] + list(domain or []))
        periods = self._workbench_periods(snapshot, period_mode, period_breaks)
        month_to_period = {m: p['key'] for p in periods for m in p['months']}

        amounts = defaultdict(lambda: defaultdict(float))
        for inv in self.env['collection.snapshot.invoice'].search_read(
                [('line_id', 'in', lines.ids)], ['line_id', 'period_key', 'amount_due_at_pull']):
            amounts[inv['line_id'][0]][month_to_period.get(inv['period_key'])] += inv['amount_due_at_pull']

        latest, counts = self._latest_notes_by_partner(lines.partner_id)
        message_counts = dict(self.env['mail.message']._read_group(
            [('model', '=', self._name), ('res_id', 'in', lines.ids),
             ('message_type', 'in', ('comment', 'email'))], ['res_id'], ['__count']))
        agreement_tags = self.env.company.collection_agreement_tag_ids
        pattern_labels = dict(self.env['res.partner']._fields['collection_pattern'].selection)
        deadline_labels = dict(self.env['res.partner']._fields['collection_deadline_state'].selection)
        rows = []
        for line in lines:
            partner = line.partner_id
            note = latest.get(partner.id)
            rows.append({
                'id': line.id,
                'partner_id': partner.id,
                'partner': partner.display_name,
                'section': line.live_section,
                'salesman': [line.salesman_id.id, line.salesman_id.name] if line.salesman_id else False,
                'assignee': [line.assignee_id.id, line.assignee_id.name] if line.assignee_id else False,
                'tags': [{'id': t.id, 'name': t.name, 'color': t.color} for t in partner.category_id],
                'is_agreement': bool(partner.category_id & agreement_tags),
                'periods': {k: v for k, v in amounts[line.id].items() if k},
                'total_due': line.total_due,
                'unreconciled_now': line.unreconciled_now,
                'soa_balance': line.soa_balance,
                'live_balance': line.live_balance,
                'live_collected': line.live_collected,
                'live_status': line.live_status,
                'changed_invoice_count': line.changed_invoice_count,
                'pay_check': line.pay_check or False,
                'pipeline': partner.collection_pipeline_id.name or False,
                'stage': partner.collection_stage_id.name or False,
                'next_action': partner.collection_next_action or False,
                'due_to_send': partner.collection_due_to_send,
                'awaiting_approval': partner.collection_awaiting_approval,
                'customer_replied': line.customer_replied,
                'pattern': partner.collection_pattern,
                'pattern_label': pattern_labels.get(partner.collection_pattern),
                'deadline_state': partner.collection_deadline_state,
                'deadline_label': deadline_labels.get(partner.collection_deadline_state),
                'deadline_date': format_date(self.env, partner.collection_deadline_date)
                if partner.collection_deadline_date else False,
                'credit_limit': partner.commercial_partner_id.sudo().credit_limit,
                'message_count': message_counts.get(line.id, 0),
                'note': note and {
                    'category': note.category_id.name,
                    'category_id': note.category_id.id,
                    'color': note.category_id.color,
                    'date': format_date(self.env, note.date),
                    'body': note.body or '',
                    'promise_date': format_date(self.env, note.promise_date) if note.promise_date else False,
                    'amount': note.amount,
                    'is_system': note.is_system,
                    'count': counts.get(partner.id, 0),
                } or False,
            })
        return {
            'snapshot': {
                'id': snapshot.id,
                'name': snapshot.name,
                'state': snapshot.state,
                'is_latest': snapshot.is_latest,
                'pull_date': format_date(self.env, snapshot.pull_date) if snapshot.pull_date else False,
            },
            'currency': {'symbol': snapshot.currency_id.symbol, 'position': snapshot.currency_id.position,
                         'digits': snapshot.currency_id.decimal_places},
            'periods': periods,
            'all_months': [{'key': k, 'label': self._month_label(k)}
                           for k in sorted(set(snapshot.invoice_ids.mapped('period_key')))],
            'rows': rows,
            'summary': snapshot._live_summary(),
            'categories': [{'id': c.id, 'name': c.name, 'color': c.color}
                           for c in self.env['collection.note.category'].search([])],
        }

    def write(self, vals):
        # "Change the assignee": every Collections user (Appendix B), even
        # without the right to edit contacts.
        if 'assignee_id' in vals:
            vals = dict(vals)
            employee_id = vals.pop('assignee_id')
            self.partner_id._collection_check_user()
            self.partner_id.sudo().write({'collection_assignee_id': employee_id or False})
            if not vals:
                return True
        return super().write(vals)

    @api.model
    def workbench_set_assignee(self, line_id, employee_id):
        self.browse(line_id).exists().write({'assignee_id': employee_id or False})
        return True

    # ------------------------------------------------------------------
    # RPC: the side panel (FR-35, FR-36)
    # ------------------------------------------------------------------
    @api.model
    def workbench_panel(self, line_id, note_offset=0):
        line = self.browse(line_id).exists()
        if not line:
            return False
        partner = line.partner_id._collection_fresh()
        currency = line.currency_id
        Note = self.env['collection.note']
        notes = Note.search([('partner_id', '=', partner.id), ('is_system', '=', False)],
                            order='create_date desc, id desc', limit=note_offset + 6)
        log = Note.search([('partner_id', '=', partner.id), ('is_system', '=', True)],
                          order='create_date desc, id desc', limit=15)
        employees = self.env.company.collection_employee_ids or self.env['hr.employee'].search(
            [('company_id', 'in', [False, self.env.company.id])])
        emails = self.env['mail.message'].search([
            ('model', '=', 'res.partner'), ('res_id', '=', partner.id),
            ('message_type', 'in', ('email', 'comment')),
            ('subtype_id', '=', self.env.ref('mail.mt_comment').id),
        ], limit=30)
        return {
            'line_id': line.id,
            'partner_id': partner.id,
            'name': partner.display_name,
            'email': partner.email or False,
            'phone': partner.phone or False,
            'balance': partner.collection_open_balance,
            'unreconciled': partner.collection_unreconciled,
            'last_payment': format_date(self.env, partner.collection_last_payment_date)
            if partner.collection_last_payment_date else False,
            'tags': [{'name': t.name, 'color': t.color} for t in partner.category_id],
            'salesman': line.salesman_id.name or False,
            'assignee_id': line.assignee_id.id or False,
            'employees': [[e.id, e.name] for e in employees],
            'pipeline': partner.collection_pipeline_id.name or False,
            'stage': partner.collection_stage_id.name or False,
            'credit_limit': partner.commercial_partner_id.sudo().credit_limit,
            'next_action': partner.collection_next_action or False,
            'due_to_send': partner.collection_due_to_send,
            'suggest_blacklist': partner.collection_suggest_blacklist,
            'suggest_close': partner.collection_suggest_close,
            'awaiting_approval': partner.collection_awaiting_approval,
            'pattern': dict(partner._fields['collection_pattern'].selection).get(partner.collection_pattern),
            'deadline': dict(partner._fields['collection_deadline_state'].selection).get(
                partner.collection_deadline_state),
            'deadline_date': format_date(self.env, partner.collection_deadline_date)
            if partner.collection_deadline_date else False,
            'notes': [self._panel_note(n) for n in notes[:note_offset + 5]],
            'has_older_notes': len(notes) > note_offset + 5,
            'log': [self._panel_note(n) for n in log],
            'cycles': [{'start': format_date(self.env, c.date_start), 'end': format_date(self.env, c.date_end),
                        'days': c.days, 'top': c.max_stage_id.name or '', 'partial': c.had_partial}
                       for c in partner.collection_cycle_ids],
            'emails': [{
                'id': m.id, 'date': fields.Datetime.to_string(m.date), 'subject': m.subject or '',
                'author': m.author_id.name or m.email_from or '',
                'incoming': m.message_type == 'email',
                'body': m.body,
                'failed': any(n.notification_status in ('exception', 'bounce') for n in m.notification_ids),
            } for m in emails],
            'currency': {'symbol': currency.symbol, 'position': currency.position},
        }

    @api.model
    def _panel_note(self, note):
        return {
            'id': note.id, 'category': note.category_id.name, 'color': note.category_id.color,
            'date': format_date(self.env, note.date), 'body': note.body or '', 'user': note.user_id.name,
            'channel': dict(note._fields['channel'].selection).get(note.channel) if note.channel else False,
            'promise_date': format_date(self.env, note.promise_date) if note.promise_date else False,
            'amount': note.amount or 0.0,
        }

    @api.model
    def workbench_open_invoices(self, partner_id):
        """Standard invoice list, customer + unpaid (FR-36)."""
        partner = self.env['res.partner'].browse(partner_id)
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_out_invoice_type')
        action.update({
            'name': _("Open invoices: %s", partner.display_name),
            'domain': [('move_type', 'in', ('out_invoice', 'out_receipt', 'out_refund')),
                       ('partner_id', 'child_of', partner.commercial_partner_id.id),
                       ('state', '=', 'posted'), ('payment_state', 'in', ('not_paid', 'partial'))],
            'context': {'default_move_type': 'out_invoice', 'create': False},
        })
        return action

    # ------------------------------------------------------------------
    # RPC: the dashboard (FR-38)
    # ------------------------------------------------------------------
    @api.model
    def dashboard_data(self, scope=None):
        Snapshot = self.env['collection.snapshot']
        snapshot = Snapshot._get_latest()
        is_team_user = self.env.user.has_group('collections_workbench.group_collection_accountant')
        if not scope:
            # like the simulation: the accountant / manager opens on the team view
            scope = 'team' if is_team_user else 'mine'
        if scope == 'team' and not is_team_user:
            scope = 'mine'
        base = [('snapshot_id', '=', snapshot.id)]
        if scope == 'mine':
            base.append(('assignee_user_id', '=', self.env.uid))
        lines = self.search(base) if snapshot else self.browse()
        partners = lines.partner_id
        approvals = self.env['collection.approval'].search_count(
            [('state', '=', 'pending')] + ([] if scope == 'team' else [('partner_id', 'in', partners.ids)]))
        activity_domain = [('res_model', '=', self._name), ('res_id', 'in', lines.ids)]
        if scope == 'mine':
            activity_domain += [('user_id', '=', self.env.uid),
                                ('date_deadline', '<=', fields.Date.context_today(self))]
        activities = self.env['mail.activity'].search_count(activity_domain)

        def count(pred):
            return len(lines.filtered(pred))

        cards = [
            {'key': 'overdue', 'label': _("Promises overdue"), 'help': _("Call them today: they missed the date they promised."),
             'value': count(lambda l: l.partner_id.collection_deadline_state == 'late'), 'tone': 'danger',
             'filter': 'deadline_late'},
            {'key': 'today', 'label': _("Due today"), 'help': _("Customers who promised to pay or meet today."),
             'value': count(lambda l: l.partner_id.collection_deadline_state == 'today'), 'tone': 'warning',
             'filter': 'deadline_today'},
            {'key': 'send', 'label': _("Ready to send"), 'help': _("The next reminder is due: open and click Follow up."),
             'value': count(lambda l: l.partner_id.collection_due_to_send and not l.unreconciled_now), 'tone': 'primary',
             'filter': 'due_to_send'},
            {'key': 'replied', 'label': _("Customer replied"), 'help': _("Read their email and answer."),
             'value': count(lambda l: l.customer_replied), 'tone': 'info', 'filter': 'replied'},
            ({'key': 'activities', 'label': _("My activities"), 'help': _("Tasks assigned to you, due today or late."),
              'value': activities, 'tone': 'secondary', 'filter': 'my_activities'} if scope == 'mine' else
             {'key': 'activities', 'label': _("Open activities"), 'help': _("Tasks waiting on someone in the team."),
              'value': activities, 'tone': 'secondary', 'filter': 'open_activities'}),
            {'key': 'approvals', 'label': _("Awaiting approval"), 'help': _("VIP requests waiting for the owner or manager."),
             'value': approvals, 'tone': 'warning', 'action': 'approvals'},
            {'key': 'mismatch', 'label': _("Payment mismatches"), 'help': _("The note and the bank do not agree: check them."),
             'value': count(lambda l: l.pay_check in MISMATCHES), 'tone': 'danger', 'filter': 'mismatches'},
            {'key': 'unrec', 'label': _("Unreconciled"), 'help': _("Payments not matched with invoices: emails are blocked."),
             'value': count(lambda l: l.unreconciled_now > 0.005), 'tone': 'dark', 'filter': 'unreconciled'},
            {'key': 'late_us', 'label': _("Late on our side"), 'help': _("Our own visits or calls not done on time."),
             'value': count(lambda l: l.partner_id.collection_deadline_state == 'late_us'), 'tone': 'warning',
             'filter': 'deadline_late_us'},
            {'key': 'blacklist', 'label': _("Final notice expired"), 'help': _("Blacklist is suggested: decide and move them."),
             'value': count(lambda l: l.partner_id.collection_suggest_blacklist), 'tone': 'danger',
             'filter': 'suggest_blacklist'},
            {'key': 'close', 'label': _("Lane fully paid"), 'help': _("Paid in full in Agreements or Legal Cases: close them."),
             'value': count(lambda l: l.partner_id.collection_suggest_close), 'tone': 'success',
             'filter': 'suggest_close'},
            {'key': 'thanks', 'label': _("Thank-you due"), 'help': _("A payment arrived: send a thank-you email."),
             'value': count(lambda l: l.partner_id.collection_thanks_due and not l.unreconciled_now), 'tone': 'success',
             'filter': 'thanks_due'},
        ]
        priority = {'late': 0, 'today': 1}

        def rank(l):
            state = l.partner_id.collection_deadline_state
            if state in priority:
                return priority[state]
            if l.customer_replied or l.partner_id.collection_due_to_send:
                return 2
            return 3  # late on our side

        queue = sorted(
            lines.filtered(lambda l: l.partner_id.collection_deadline_state in ('late', 'today', 'late_us')
                           or l.partner_id.collection_due_to_send or l.customer_replied),
            key=lambda l: (rank(l), -l.total_due))[:10]
        workload = defaultdict(lambda: {'customers': 0, 'due': 0.0, 'collected': 0.0})
        for line in lines:
            w = workload[line.assignee_id.name or _("Unassigned")]
            w['customers'] += 1
            w['due'] += line.total_due
            w['collected'] += line.live_collected
        return {
            'snapshot': snapshot.name or False,
            'scope': scope,
            'can_team': is_team_user,
            'cards': cards,
            'queue': [{
                'line_id': l.id, 'partner': l.partner_id.display_name, 'total_due': l.total_due,
                'why': (_("Promise overdue") if l.partner_id.collection_deadline_state == 'late'
                        else _("Due today") if l.partner_id.collection_deadline_state == 'today'
                        else _("Customer replied") if l.customer_replied
                        else _("Send: %s", l.partner_id.collection_next_action or '')
                        if l.partner_id.collection_due_to_send else _("Late on our side")),
            } for l in queue],
            'workload': sorted(({'name': k, **v, 'rate': v['collected'] / v['due'] if v['due'] else 0.0}
                                for k, v in workload.items()), key=lambda w: -w['due']),
            'currency': {'symbol': self.env.company.currency_id.symbol,
                         'position': self.env.company.currency_id.position},
        }
