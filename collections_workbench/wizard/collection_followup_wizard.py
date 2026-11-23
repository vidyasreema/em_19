from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.collection_note import CHANNELS

KINDS = [
    ('note', 'Log a note'),
    ('stage', 'Move to a stage'),
    ('soa', 'Statement of account'),
    ('thanks', 'Thank you for payment'),
    ('remain', 'Remaining balance request'),
    ('custom', 'Custom message'),
]
EVENT_TEMPLATES = {
    'soa': 'collections_workbench.mail_template_soa',
    'thanks': 'collections_workbench.mail_template_thanks',
    'remain': 'collections_workbench.mail_template_remain',
    'custom': 'collections_workbench.mail_template_custom',
}


class CollectionFollowupWizard(models.TransientModel):
    """"Follow up" dialog (FR-22, FR-25): preview per customer, blocked
    customers listed by name and reason, VIP routed to Approvals."""
    _name = 'collection.followup.wizard'
    _description = 'Collections: Follow up'

    partner_ids = fields.Many2many('res.partner', string="Customers", required=True)
    partner_count = fields.Integer(compute='_compute_partner_count')
    kind = fields.Selection(KINDS, string="What to do", required=True, default='stage')
    pipeline_id = fields.Many2one(
        'collection.pipeline', string="Pipeline", default=lambda self: self._default_pipeline())
    stage_id = fields.Many2one(
        'collection.stage', string="Stage", domain="[('pipeline_id', '=', pipeline_id)]",
        compute='_compute_stage_id', store=True, readonly=False)
    stage_has_email = fields.Boolean(related='stage_id.has_email')
    send_mode = fields.Selection(
        [('email', 'Send the email'), ('record', 'Record without email')],
        string="How", compute='_compute_send_mode', store=True, readonly=False)
    channel = fields.Selection(
        [c for c in CHANNELS if c[0] != 'email'], string="Channel", default='call')
    note = fields.Text(string="Note", help="What happened (saved with the system note).")
    template_id = fields.Many2one(
        'mail.template', string="Template", domain=[('model', '=', 'res.partner')],
        compute='_compute_template_id', store=True, readonly=False)
    deadline_date = fields.Date(
        string="Deadline", compute='_compute_deadline_date', store=True, readonly=False,
        help="Used in the email as the settlement deadline.")
    show_deadline = fields.Boolean(compute='_compute_deadline_date', store=True)
    subject = fields.Char(compute='_compute_email', store=True, readonly=False)
    body = fields.Html(compute='_compute_email', store=True, readonly=False, sanitize_style=True)
    uses_email = fields.Boolean(compute='_compute_uses_email')
    preview_html = fields.Html(compute='_compute_preview_html', sanitize=False)

    # "Log a note" (FR-15)
    note_category_id = fields.Many2one(
        'collection.note.category', string="Category", domain=[('is_system', '=', False)])
    note_requires_date = fields.Boolean(related='note_category_id.requires_date')
    note_requires_amount = fields.Boolean(related='note_category_id.requires_amount')
    note_promise_date = fields.Date(string="Date")
    note_amount = fields.Monetary(string="Amount", currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    show_full_history = fields.Boolean(string="Full history")
    history_html = fields.Html(compute='_compute_history_html', sanitize=False)
    pipeline_change_info = fields.Char(compute='_compute_preview_html')

    @api.model
    def _default_pipeline(self):
        partners = self.env['res.partner'].browse(self.env.context.get('default_partner_ids') or [])
        if len(partners) == 1 and partners.collection_pipeline_id:
            return partners.collection_pipeline_id
        return self.env['collection.pipeline']._get_collection()

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        for wiz in self:
            wiz.partner_count = len(wiz.partner_ids)

    @api.depends('pipeline_id', 'kind')
    def _compute_stage_id(self):
        for wiz in self:
            if wiz.kind != 'stage' or (wiz.stage_id and wiz.stage_id.pipeline_id == wiz.pipeline_id):
                wiz.stage_id = wiz.stage_id
                continue
            suggested = wiz.partner_ids[:1].collection_next_stage_id if wiz.partner_count == 1 else False
            if suggested and suggested.pipeline_id == wiz.pipeline_id:
                wiz.stage_id = suggested
            else:
                wiz.stage_id = wiz.pipeline_id.stage_ids.filtered(lambda s: not s.is_partial)[:1]

    @api.depends('stage_id', 'kind')
    def _compute_send_mode(self):
        for wiz in self:
            if wiz.kind != 'stage':
                wiz.send_mode = 'email'
            elif not wiz.stage_id.has_email:
                wiz.send_mode = 'record'
            elif not wiz.send_mode:
                wiz.send_mode = 'email'

    @api.depends('kind', 'stage_id')
    def _compute_template_id(self):
        for wiz in self:
            if wiz.kind == 'stage':
                wiz.template_id = wiz.stage_id.template_id
            elif wiz.kind == 'note':
                wiz.template_id = False
            else:
                wiz.template_id = self.env.ref(EVENT_TEMPLATES[wiz.kind], raise_if_not_found=False)

    @api.depends('kind', 'stage_id')
    def _compute_deadline_date(self):
        today = fields.Date.context_today(self)
        company = self.env.company
        for wiz in self:
            if wiz.kind == 'remain':
                wiz.show_deadline = True
                wiz.deadline_date = fields.Date.add(today, days=company.collection_partial_wait)
            elif wiz.kind == 'stage' and wiz.stage_id.suggests_blacklist:
                wiz.show_deadline = True
                wiz.deadline_date = fields.Date.add(today, days=wiz.stage_id.wait_days)
            else:
                wiz.show_deadline = False
                wiz.deadline_date = False

    @api.depends('kind', 'send_mode')
    def _compute_uses_email(self):
        for wiz in self:
            if wiz.kind == 'note':
                wiz.uses_email = False
            elif wiz.kind == 'stage':
                wiz.uses_email = wiz.send_mode == 'email'
            else:
                wiz.uses_email = True

    @api.depends('template_id', 'deadline_date', 'partner_ids')
    def _compute_email(self):
        for wiz in self:
            partner = wiz.partner_ids[:1]._origin
            if partner and wiz.template_id:
                wiz.subject, wiz.body = partner._collection_render(wiz.template_id, wiz.deadline_date)
            else:
                wiz.subject, wiz.body = False, False

    @api.depends('partner_ids', 'show_full_history')
    def _compute_history_html(self):
        for wiz in self:
            if wiz.partner_count != 1:
                wiz.history_html = False
                continue
            notes = self.env['collection.note'].search(
                [('partner_id', '=', wiz.partner_ids._origin.id)], order='create_date desc, id desc',
                limit=None if wiz.show_full_history else 3)
            rows = [Markup(
                '<tr><td class="text-nowrap">%s</td><td><span class="badge o_tag_color_%s">%s</span></td>'
                '<td>%s</td><td class="text-muted text-nowrap">%s</td></tr>'
            ) % (fields.Date.to_string(n.date), n.category_id.color or 0, n.category_id.name,
                 n.body or '', n.user_id.name) for n in notes]
            wiz.history_html = Markup(
                '<table class="table table-sm mb-0"><tbody>%s</tbody></table>') % Markup('').join(rows) \
                if rows else Markup('<p class="text-muted">%s</p>') % _("No notes yet.")

    # ------------------------------------------------------------------
    # Outcome per customer (VR-7..10, AC-14)
    # ------------------------------------------------------------------
    def _outcome(self, partner):
        """(code, reason): code in send / record / approval / blocked."""
        self.ensure_one()
        if self.kind == 'note':
            return 'record', ''
        email = self.uses_email
        if self.kind == 'stage':
            if not self.stage_id:
                return 'blocked', _("Choose a stage")
            current = partner.collection_pipeline_id
            if current and current != self.pipeline_id and self.partner_count > 1:
                return 'blocked', _("In another pipeline: %s", current.name)
        if email:
            reason = partner._collection_email_block_reason()
            if reason:
                return 'blocked', reason
        if self.kind == 'stage' and partner._collection_needs_approval(self.stage_id):
            return 'approval', _("VIP: goes to the Approvals queue")
        return ('send' if email else 'record'), ''

    @api.depends('partner_ids', 'kind', 'stage_id', 'send_mode', 'pipeline_id')
    def _compute_preview_html(self):
        labels = {
            'send': (_("Will be sent"), 'text-bg-success'),
            'record': (_("Will be recorded"), 'text-bg-info'),
            'approval': (_("Awaiting approval"), 'text-bg-warning'),
            'blocked': (_("Excluded"), 'text-bg-danger'),
        }
        for wiz in self:
            rows = []
            for partner in wiz.partner_ids._origin:
                code, reason = wiz._outcome(partner)
                label, css = labels[code]
                rows.append(Markup(
                    '<tr><td>%s</td><td><span class="badge %s">%s</span></td><td>%s</td></tr>'
                ) % (partner.display_name, css, label, reason))
            wiz.preview_html = Markup(
                '<table class="table table-sm mb-0"><thead><tr><th>%s</th><th>%s</th><th>%s</th>'
                '</tr></thead><tbody>%s</tbody></table>'
            ) % (_("Customer"), _("Result"), _("Reason"), Markup('').join(rows))
            info = False
            if wiz.kind == 'stage' and wiz.partner_count == 1:
                current = wiz.partner_ids._origin.collection_pipeline_id
                if current and wiz.pipeline_id and current != wiz.pipeline_id:
                    info = _("This moves the customer from %(old)s to %(new)s.",
                             old=current.name, new=wiz.pipeline_id.name)
            wiz.pipeline_change_info = info

    # ------------------------------------------------------------------
    def _log_notes(self):
        if not self.note_category_id:
            raise UserError(_("Choose a note category."))
        self.env['collection.note'].create([{
            'partner_id': partner.id,
            'category_id': self.note_category_id.id,
            'body': self.note or False,
            'promise_date': self.note_promise_date if self.note_requires_date else False,
            'amount': self.note_amount if self.note_requires_amount else 0.0,
        } for partner in self.partner_ids])
        return {'type': 'ir.actions.act_window_close'}

    def action_toggle_history(self):
        self.show_full_history = not self.show_full_history
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new', 'name': _("Follow up"), 'context': self.env.context,
        }

    def action_confirm(self):
        self.ensure_one()
        self.partner_ids._collection_check_user()
        if self.kind == 'stage' and not self.stage_id:
            raise UserError(_("Choose a stage."))
        if self.kind == 'stage' and self.send_mode == 'record' and not self.channel:
            raise UserError(_("Choose how the customer was contacted."))
        if self.uses_email and not self.template_id and not self.body:
            raise UserError(_("Write the email or choose a template."))
        if self.kind == 'note':
            return self._log_notes()
        single = self.partner_count == 1
        done, approvals, skipped = [], [], []
        for partner in self.partner_ids:
            code, reason = self._outcome(partner)
            if code == 'blocked':
                if single:
                    raise UserError(_("%(customer)s: %(reason)s.", customer=partner.display_name, reason=reason))
                skipped.append('%s (%s)' % (partner.display_name, reason))
                continue
            if self.uses_email:
                if single:
                    subject, body = self.subject, self.body
                else:
                    subject, body = partner._collection_render(self.template_id, self.deadline_date)
            else:
                subject, body = False, False
            channel = 'email' if self.uses_email else self.channel
            if self.kind != 'stage':
                partner._collection_send_event(self.kind, subject, body)
                done.append(partner.display_name)
            elif code == 'approval':
                partner._collection_request_approval(
                    self.stage_id, channel, note=self.note, subject=subject, body=body,
                    template=self.template_id)
                approvals.append(partner.display_name)
            else:
                partner._collection_apply_stage(self.stage_id, channel=channel, note=self.note,
                                                subject=subject, body=body)
                done.append(partner.display_name)

        parts = []
        if done:
            parts.append(_("Done: %s", ', '.join(done)))
        if approvals:
            parts.append(_("Sent to Approvals: %s", ', '.join(approvals)))
        if skipped:
            parts.append(_("Excluded: %s", '; '.join(skipped)))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Follow up"),
                'message': '\n'.join(parts) or _("Nothing to do."),
                'type': 'warning' if skipped or approvals else 'success',
                'sticky': bool(skipped),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
