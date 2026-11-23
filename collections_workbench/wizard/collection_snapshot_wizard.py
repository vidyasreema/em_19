from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import formatLang, html_escape


class CollectionSnapshotWizard(models.TransientModel):
    _name = 'collection.snapshot.wizard'
    _description = 'New Collection Snapshot'

    period_type = fields.Selection(
        [('before_month', 'Before month'), ('range', 'From date to date')],
        string="Period", required=True, default='before_month')
    month_date = fields.Date(
        string="Before month",
        default=lambda self: fields.Date.context_today(self).replace(day=1),
        help="Invoices dated before the first day of this month.")
    date_from = fields.Date(string="From")
    date_to = fields.Date(string="To")
    unreconciled_html = fields.Html(compute='_compute_preview', sanitize=False)
    unreconciled_count = fields.Integer(compute='_compute_preview')
    invoice_count = fields.Integer(compute='_compute_preview')
    customer_count = fields.Integer(compute='_compute_preview')
    duplicate_info = fields.Char(compute='_compute_preview')

    def _snapshot_vals(self):
        self.ensure_one()
        vals = {'period_type': self.period_type, 'company_id': self.env.company.id}
        if self.period_type == 'before_month':
            if not self.month_date:
                raise UserError(_("Choose the month."))
            vals['month_date'] = self.month_date.replace(day=1)
        else:
            if not (self.date_from and self.date_to) or self.date_from > self.date_to:
                raise UserError(_("Choose a valid date range."))
            vals.update(date_from=self.date_from, date_to=self.date_to)
        return vals

    @api.depends('period_type', 'month_date', 'date_from', 'date_to')
    def _compute_preview(self):
        Snapshot = self.env['collection.snapshot']
        for wiz in self:
            wiz.unreconciled_html = False
            wiz.duplicate_info = False
            wiz.unreconciled_count = wiz.invoice_count = wiz.customer_count = 0
            try:
                vals = wiz._snapshot_vals()
            except UserError:
                continue
            same = Snapshot.search([(k, '=', v) for k, v in vals.items()] + [
                ('state', '!=', 'archived')], order='pull_date desc', limit=1)
            if same:
                wiz.duplicate_info = _(
                    '"%(name)s" already exists (pulled on %(date)s by %(user)s). To pull it again, '
                    'archive the existing one first (Snapshots > All snapshots > open it > Archive).',
                    name=same.name, user=same.generated_by.name,
                    date=fields.Datetime.context_timestamp(self, same.pull_date).strftime('%d/%m/%Y %H:%M')
                    if same.pull_date else _("now"))
            probe = Snapshot.new(vals)
            moves = self.env['account.move'].sudo().search(probe._invoice_domain())
            partners = moves.partner_id
            wiz.invoice_count = len(moves)
            wiz.customer_count = len(partners)
            unrec = partners._collection_unreconciled_by_partner()
            flagged = partners.filtered(lambda p: unrec.get(p.id, 0) > 0.005).sorted(
                lambda p: -unrec[p.id])
            wiz.unreconciled_count = len(flagged)
            if flagged:
                currency = self.env.company.currency_id
                rows = ''.join(
                    '<tr><td>%s</td><td class="text-end">%s</td></tr>' % (
                        html_escape(p.display_name), formatLang(self.env, unrec[p.id], currency_obj=currency))
                    for p in flagged)
                wiz.unreconciled_html = (
                    '<table class="table table-sm o_collection_unrec_table">'
                    '<thead><tr><th>%s</th><th class="text-end">%s</th></tr></thead>'
                    '<tbody>%s</tbody></table>' % (_("Customer"), _("Unreconciled"), rows))

    def action_generate(self):
        self.ensure_one()
        if not self.env.user.has_group('collections_workbench.group_collection_accountant'):
            raise AccessError(_("Only the accountant or the manager can generate a snapshot."))
        if self.duplicate_info:
            raise UserError(self.duplicate_info)
        snapshot = self.env['collection.snapshot'].create(self._snapshot_vals())
        cron = self.env.ref('collections_workbench.ir_cron_generate_snapshot', raise_if_not_found=False)
        if not (cron and cron.sudo().active):
            # background job switched off (e.g. a test copy): build it now
            snapshot.sudo()._generate()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'title': _("Snapshot ready"),
                    'message': _("%(name)s: %(customers)s customers, %(invoices)s invoices.",
                                 name=snapshot.name, customers=snapshot.customer_count,
                                 invoices=snapshot.invoice_count),
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        cron.sudo()._trigger()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'title': _("Snapshot is being generated"),
                'message': _("%s: you will be notified in your Inbox when it is ready.",
                             snapshot.name),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
