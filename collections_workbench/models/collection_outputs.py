"""Outputs (FR-37, FR-39, Appendix D): Excel export with the table's
colour-coded layout, individual statements, the statement package built in
the background, and the one-page monthly report."""
import base64
import io
import logging
import zipfile
from collections import defaultdict

import xlsxwriter

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_date

from .collection_columns import COLUMNS, PAY_CHECK_LABELS, SECTIONS, STATUS_LABELS, columns_for_client

_logger = logging.getLogger(__name__)


class CollectionSnapshotLine(models.Model):
    _inherit = 'collection.snapshot.line'

    def _search_live_status(self, operator, value):
        values = [value] if isinstance(value, str) else list(value)
        if operator not in ('in', '='):
            raise UserError(_("Unsupported filter on the status."))
        lines = self.search([('snapshot_id.state', '!=', 'generating')])
        return [('id', 'in', lines.filtered(lambda l: l.live_status in values).ids)]

    @api.model
    def workbench_columns(self):
        return columns_for_client()

    # ------------------------------------------------------------------
    # Excel (same colour-coded layout as the table)
    # ------------------------------------------------------------------
    @api.model
    def _workbench_xlsx(self, data, column_keys=None):
        """xlsx bytes for workbench_data() output."""
        visible = [c for c in COLUMNS if (column_keys is None and c[4]) or (column_keys and c[0] in column_keys)]
        section_colors = {k: c for k, _l, c in SECTIONS}
        section_labels = {k: l for k, l, _c in SECTIONS}
        # table order: customer, periods, then the other sections
        ordered = [c for c in visible if c[2] == 'customer']
        periods = data['periods'] if (column_keys is None or 'periods' in column_keys) else []
        tail = [c for c in visible if c[2] != 'customer']

        out = io.BytesIO()
        book = xlsxwriter.Workbook(out, {'in_memory': True})
        sheet = book.add_worksheet((data['snapshot']['name'] or 'Snapshot')[:31])
        fmt = {}

        def style(color, bold=False, num=False, border=1):
            key = (color, bold, num)
            if key not in fmt:
                opts = {'border': border, 'border_color': '#CCCCCC', 'valign': 'vcenter'}
                if color:
                    opts['bg_color'] = color
                if bold:
                    opts['bold'] = True
                if num:
                    opts['num_format'] = '#,##0.00'
                fmt[key] = book.add_format(opts)
            return fmt[key]

        headers = []   # (section key, label, getter, kind)
        for c in ordered:
            headers.append((c[2], c[1], c[0], c[3]))
        for p in periods:
            headers.append(('periods', p['label'], ('period', p['key']), 'money'))
        for c in tail:
            headers.append((c[2], c[1], c[0], c[3]))

        # row 0: sections (merged), row 1: columns
        col = 0
        while col < len(headers):
            sec = headers[col][0]
            end = col
            while end + 1 < len(headers) and headers[end + 1][0] == sec:
                end += 1
            cell_style = style(section_colors[sec], bold=True)
            if end > col:
                sheet.merge_range(0, col, 0, end, section_labels[sec], cell_style)
            else:
                sheet.write(0, col, section_labels[sec], cell_style)
            col = end + 1
        for i, (sec, label, _key, kind) in enumerate(headers):
            sheet.write(1, i, label, style(section_colors[sec], bold=True))
            sheet.set_column(i, i, 34 if i == 0 else (40 if kind == 'note' else 16))
        sheet.freeze_panes(2, 1)

        def value(row, key, kind):
            if isinstance(key, tuple):
                return row['periods'].get(key[1], 0.0) or None
            val = row.get(key)
            if kind == 'm2o':
                return val[1] if val else ''
            if kind == 'tags':
                return ', '.join(t['name'] for t in val or [])
            if kind == 'note':
                return ('%s %s: %s' % (val['date'], val['category'], val['body'])) if val else ''
            if key == 'live_status':
                return STATUS_LABELS.get(val, '')
            if key == 'pay_check':
                return PAY_CHECK_LABELS.get(val, '') if val else ''
            return val if val not in (False, None) else ''

        r = 2
        section_names = dict(self.env['collection.snapshot.line']._fields['section'].selection)
        totals_all = defaultdict(float)
        for section in ('active', 'court', 'blacklist'):
            rows = [x for x in data['rows'] if x['section'] == section]
            if not rows:
                continue
            sheet.merge_range(r, 0, r, len(headers) - 1, section_names[section], style('#DDDDDD', bold=True))
            r += 1
            totals = defaultdict(float)
            for row in rows:
                for i, (sec, _label, key, kind) in enumerate(headers):
                    v = value(row, key, kind)
                    is_num = kind in ('money', 'int')
                    color = None
                    if sec == 'periods' and v:
                        color = '#FFF9EC'
                    if key == 'unreconciled_now' and v:
                        color = '#FBE3E1'
                    sheet.write(r, i, v, style(color, num=is_num and kind == 'money'))
                    if kind == 'money' and v:
                        totals[i] += v
                        totals_all[i] += v
                r += 1
            sheet.write(r, 0, _("Subtotal %s", section_names[section]), style('#EEEEEE', bold=True))
            for i in range(1, len(headers)):
                sheet.write(r, i, totals.get(i) or '', style('#EEEEEE', bold=True, num=True))
            r += 1
        sheet.write(r, 0, _("Grand total"), style('#CFE2CF', bold=True))
        for i in range(1, len(headers)):
            sheet.write(r, i, totals_all.get(i) or '', style('#CFE2CF', bold=True, num=True))
        book.close()
        return out.getvalue()

    @api.model
    def workbench_export(self, snapshot_id, domain=None, period_mode='default', column_keys=None,
                         period_breaks=None):
        data = self.workbench_data(snapshot_id, domain or [], period_mode, period_breaks)
        if not data.get('snapshot'):
            raise UserError(_("Choose a snapshot first."))
        content = self._workbench_xlsx(data, column_keys)
        attachment = self.env['ir.attachment'].create({
            'name': '%s.xlsx' % data['snapshot']['name'],
            'datas': base64.b64encode(content),
            'res_model': 'collection.snapshot',
            'res_id': snapshot_id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return '/web/content/%s?download=true' % attachment.id

    # ------------------------------------------------------------------
    # Individual statement (FR-37)
    # ------------------------------------------------------------------
    @api.model
    def workbench_statement(self, partner_id, mode='statement'):
        partner = self.env['res.partner'].browse(partner_id)
        partner._collection_check_user()
        reason = partner._collection_fresh().collection_unreconciled > 0.005
        if reason:
            raise UserError(_("%s has an unreconciled payment: reconcile it before sending a statement.",
                              partner.display_name))
        report = self.env.ref('collections_workbench.action_report_statement')
        return report.report_action(partner, data={'mode': mode})


class CollectionStatementReport(models.AbstractModel):
    """Statement of account / Ledger, full period by default (FR-37)."""
    _name = 'report.collections_workbench.report_statement'
    _description = 'Collections: statement of account'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        mode = data.get('mode', 'statement')
        docids = docids or (data.get('context') or {}).get('active_ids') or []
        partners = self.env['res.partner'].browse(docids)
        if not self.env.user.has_group('collections_workbench.group_collection_user'):
            raise AccessError(_("Only Collections users can print statements."))
        AML = self.env['account.move.line'].sudo()
        today = fields.Date.context_today(self)
        docs = []
        for partner in partners:
            commercial = partner.commercial_partner_id
            domain = [('partner_id', '=', commercial.id), ('account_type', '=', 'asset_receivable'),
                      ('parent_state', '=', 'posted'), ('company_id', '=', self.env.company.id)]
            if mode == 'statement':
                lines = AML.search(domain + [('reconciled', '=', False), ('amount_residual', '!=', 0)],
                                   order='date, id')
                rows = [{
                    'date': l.date, 'number': l.move_id.name, 'ref': l.move_id.ref or l.name or '',
                    'due': l.date_maturity, 'amount': l.balance, 'open': l.amount_residual,
                    'overdue': max(0, (today - l.date_maturity).days) if l.date_maturity and l.amount_residual > 0 else 0,
                } for l in lines]
                total = sum(r['open'] for r in rows)
            else:
                lines = AML.search(domain, order='date, id')
                running = 0.0
                rows = []
                for l in lines:
                    running += l.balance
                    rows.append({'date': l.date, 'number': l.move_id.name, 'ref': l.move_id.ref or l.name or '',
                                 'debit': l.debit, 'credit': l.credit, 'balance': running})
                total = running
            docs.append({'partner': commercial, 'rows': rows, 'total': total})
        return {
            'doc_ids': docids,
            'doc_model': 'res.partner',
            'docs': docs,
            'mode': mode,
            'today': today,
            'company': self.env.company,
            'currency': self.env.company.currency_id,
        }


class CollectionMonthlyReport(models.AbstractModel):
    """One-page monthly report (FR-39, AC-29)."""
    _name = 'report.collections_workbench.report_monthly'
    _description = 'Collections: monthly report'

    @api.model
    def _figures(self, lines, total_due=None):
        due = sum(lines.mapped('total_due'))
        collected = sum(lines.mapped('live_collected'))
        statuses = lines.mapped('live_status')
        return {'count': len(lines), 'due': due, 'collected': collected,
                'balance': due - collected, 'rate': collected / due if due else 0.0,
                'share': due / total_due if total_due else 0.0,
                'paid': statuses.count('paid'), 'partly': statuses.count('partly'),
                'not_paid': statuses.count('none')}

    @api.model
    def _snapshot_report(self, snap):
        """Everything the monthly report shows, for the PDF and the Report page."""
        lines = snap.line_ids
        agreement_tags = snap.company_id.collection_agreement_tag_ids
        # current tags, as on the table (BR-20)
        blacklist = lines.filtered(lambda l: l.live_section == 'blacklist')
        court = lines.filtered(lambda l: l.live_section == 'court')
        agreements = lines.filtered(lambda l: l.live_section == 'active'
                                    and l.partner_id.category_id & agreement_tags)
        net = lines - blacklist - court - agreements
        total = sum(lines.mapped('total_due'))
        summary = [
            (_("Total"), self._figures(lines, total), False),
            (_("Blacklist"), self._figures(blacklist, total), False),
            (_("Court case"), self._figures(court, total), False),
            (_("Agreements"), self._figures(agreements, total), False),
            (_("Net total"), self._figures(net, total), True),
        ]
        live = snap._live_summary()
        live['rate_net'] = summary[-1][1]['rate']
        cycles = self.env['collection.cycle'].search([('company_id', '=', snap.company_id.id)])
        live['cycles'] = len(cycles)
        live['avg_days'] = round(sum(cycles.mapped('days')) / len(cycles)) if cycles else False
        trend_snaps = self.env['collection.snapshot'].search(
            [('state', '!=', 'generating'), ('company_id', '=', snap.company_id.id),
             ('pull_date', '<=', snap.pull_date)], order='pull_date desc', limit=6)
        trend = [{'id': s.id, 'name': s.name, **self._figures(s.line_ids)} for s in reversed(trend_snaps)]
        by_assignee = defaultdict(lambda: self.env['collection.snapshot.line'])
        for line in lines:
            by_assignee[line.assignee_id.name or _("Unassigned")] |= line
        assignees = sorted(({'name': k, **self._figures(v)} for k, v in by_assignee.items()),
                           key=lambda a: -a['due'])
        return {'snapshot': snap, 'summary': summary, 'live': live, 'trend': trend,
                'assignees': assignees}

    @api.model
    def _get_report_values(self, docids, data=None):
        snapshots = self.env['collection.snapshot'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'collection.snapshot',
            'docs': [self._snapshot_report(snap) for snap in snapshots],
            'currency': self.env.company.currency_id,
            'today': fields.Date.context_today(self),
        }


class CollectionStatementPackage(models.Model):
    """Bulk package: coloured Excel + one PDF statement per customer, built
    in the background, named "Salesperson — Period.zip" (FR-37)."""
    _name = 'collection.statement.package'
    _description = 'Collections statement package'
    _inherit = ['mail.thread']
    _order = 'id desc'

    snapshot_id = fields.Many2one('collection.snapshot', required=True, ondelete='cascade')
    salesman_id = fields.Many2one('hr.employee', string="Salesperson", help="Empty = all customers")
    state = fields.Selection([('queued', 'Queued'), ('done', 'Ready'), ('failed', 'Failed')],
                             default='queued', required=True)
    requested_by = fields.Many2one('res.users', default=lambda self: self.env.user, required=True)
    attachment_id = fields.Many2one('ir.attachment', readonly=True)
    excluded = fields.Text(readonly=True)
    name = fields.Char(compute='_compute_name', store=True)

    @api.depends('snapshot_id', 'salesman_id')
    def _compute_name(self):
        for pack in self:
            pack.name = '%s — %s' % (pack.salesman_id.name or _("All"), pack.snapshot_id.name)

    @api.model
    def _cron_build(self):
        for pack in self.search([('state', '=', 'queued')]):
            try:
                with self.env.cr.savepoint():
                    pack.with_user(pack.requested_by)._build()
            except Exception as exc:
                _logger.exception("Collections: statement package %s failed", pack.id)
                pack.state = 'failed'
                pack.message_post(body=_("The statement package failed: %s", exc),
                                  partner_ids=pack.requested_by.partner_id.ids)

    def action_build_now(self):
        """Build a package that is still waiting, right now (when the
        background job is switched off)."""
        self.env['res.partner']._collection_check_user()
        for pack in self.filtered(lambda p: p.state != 'done'):
            pack.with_user(pack.requested_by)._build()
        return True

    def _build(self):
        self.ensure_one()
        Line = self.env['collection.snapshot.line']
        domain = [('salesman_id', '=', self.salesman_id.id)] if self.salesman_id else []
        data = Line.workbench_data(self.snapshot_id.id, domain)
        lines = Line.browse([r['id'] for r in data['rows']])
        blocked = lines.filtered(lambda l: l.unreconciled_now > 0.005)
        ok = lines - blocked
        report = self.env.ref('collections_workbench.action_report_statement').sudo()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('%s.xlsx' % self.name, Line._workbench_xlsx(data))
            used = set()
            for line in ok:
                pdf, _fmt = report.with_context(lang='en_US')._render_qweb_pdf(
                    report.report_name, line.partner_id.ids, data={'mode': 'statement'})
                safe = ''.join(ch for ch in line.partner_id.display_name if ch not in '/\\:*?"<>|')[:80]
                # two customers can share a name: keep both files
                name = safe if safe.lower() not in used else '%s (%s)' % (safe, line.partner_id.id)
                used.add(name.lower())
                archive.writestr('%s.pdf' % name, pdf)
        attachment = self.env['ir.attachment'].create({
            'name': '%s.zip' % self.name,
            'datas': base64.b64encode(buffer.getvalue()),
            'res_model': self._name, 'res_id': self.id, 'mimetype': 'application/zip',
        })
        reason = _("unreconciled payment")
        excluded = '\n'.join('%s (%s)' % (l.partner_id.display_name, reason) for l in blocked)
        self.write({'state': 'done', 'attachment_id': attachment.id, 'excluded': excluded or False})
        body = _("Your statement package \"%(name)s\" is ready: %(count)s customers.",
                 name=self.name, count=len(ok))
        if blocked:
            body += ' ' + _("Excluded (unreconciled): %s", ', '.join(blocked.partner_id.mapped('display_name')))
        self.message_post(body=body, attachment_ids=attachment.ids,
                          partner_ids=self.requested_by.partner_id.ids, subtype_xmlid='mail.mt_comment')


class CollectionPackageWizard(models.TransientModel):
    _name = 'collection.package.wizard'
    _description = 'Collections: statement package'

    snapshot_id = fields.Many2one('collection.snapshot', required=True,
                                  default=lambda self: self.env['collection.snapshot']._get_latest())
    salesman_id = fields.Many2one('hr.employee', string="Salesperson", help="Empty = all customers")

    def action_build(self):
        self.ensure_one()
        self.env['res.partner']._collection_check_user()
        pack = self.env['collection.statement.package'].create({
            'snapshot_id': self.snapshot_id.id, 'salesman_id': self.salesman_id.id})
        cron = self.env.ref('collections_workbench.ir_cron_statement_package', raise_if_not_found=False)
        if not (cron and cron.sudo().active):
            # background job switched off (e.g. a test copy): one PDF per
            # customer takes minutes, so say it instead of waiting silently
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'warning', 'sticky': True, 'title': _("Statement package"),
                           'message': _('The background job "Collections: build statement packages" is '
                                        'switched off in this database. Open Snapshots > Statement packages > '
                                        '%s and click "Build now" (it takes a few minutes), or ask the '
                                        'administrator to switch the job on.', pack.name),
                           'next': {'type': 'ir.actions.act_window_close'}},
            }
        cron.sudo()._trigger()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'info', 'title': _("Statement package"),
                       'message': _("It is being built in the background. You will get it in your Inbox."),
                       'next': {'type': 'ir.actions.act_window_close'}},
        }


class CollectionReportMailWizard(models.TransientModel):
    """Email the monthly report PDF from the accountant's account to internal
    addresses (FR-39)."""
    _name = 'collection.report.mail.wizard'
    _description = 'Collections: email the monthly report'

    snapshot_id = fields.Many2one('collection.snapshot', required=True)
    user_ids = fields.Many2many('res.users', string="Send to", required=True,
                                domain=[('share', '=', False)])
    message = fields.Text(default=lambda self: _("Please find attached the monthly collection report."))

    def action_send(self):
        self.ensure_one()
        if not self.env.user.has_group('collections_workbench.group_collection_accountant'):
            raise AccessError(_("Only the accountant or the manager can send the report."))
        missing = self.user_ids.filtered(lambda u: not u.email)
        if missing:
            raise UserError(_("No email for: %s", ', '.join(missing.mapped('name'))))
        report = self.env.ref('collections_workbench.action_report_monthly')
        pdf, _fmt = report._render_qweb_pdf(report.report_name, self.snapshot_id.ids)
        name = _("Collection report %s.pdf", self.snapshot_id.name)
        attachment = self.env['ir.attachment'].create({
            'name': name, 'datas': base64.b64encode(pdf), 'mimetype': 'application/pdf',
            'res_model': 'collection.snapshot', 'res_id': self.snapshot_id.id,
        })
        sender = self.env.company.collection_sender_email or self.env.user.email_formatted
        self.snapshot_id.message_post(
            body=self.message, subject=name.replace('.pdf', ''), partner_ids=self.user_ids.partner_id.ids,
            attachment_ids=attachment.ids, email_from=sender, subtype_xmlid='mail.mt_comment')
        return {'type': 'ir.actions.act_window_close'}


class CollectionSnapshot(models.Model):
    _inherit = 'collection.snapshot'

    def action_email_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _("Email the monthly report"),
            'res_model': 'collection.report.mail.wizard', 'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new',
            'context': {'default_snapshot_id': self.id},
        }

    @api.model
    def report_page_data(self, snapshot_id=False):
        """The on-screen Report page (FR-39): same figures as the PDF."""
        snapshots = self.search([('state', '!=', 'generating'), ('company_id', '=', self.env.company.id)],
                                order='pull_date desc')
        snap = snapshots.filtered(lambda s: s.id == snapshot_id)[:1] or self._get_latest() or snapshots[:1]
        currency = self.env.company.currency_id
        result = {
            'snapshots': [{'id': s.id, 'name': s.name, 'state': s.state} for s in snapshots],
            'snapshot_id': snap.id or False,
            'can_email': self.env.user.has_group('collections_workbench.group_collection_accountant'),
            'currency': {'symbol': currency.symbol, 'position': currency.position},
        }
        if not snap:
            return result
        report = self.env['report.collections_workbench.report_monthly']._snapshot_report(snap)
        result.update({
            'name': snap.name,
            'pull_date': format_date(self.env, snap.pull_date.date()) if snap.pull_date else '',
            'today': format_date(self.env, fields.Date.context_today(self)),
            'live': report['live'],
            'summary': [{'label': label, 'total': bold, **figs} for label, figs, bold in report['summary']],
            'trend': report['trend'],
            'assignees': report['assignees'],
        })
        return result

    def action_statement_package(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _("Statement package"),
            'res_model': 'collection.package.wizard', 'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new',
            'context': {'default_snapshot_id': self.id},
        }
