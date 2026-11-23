from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError

from .collection_note import CHANNELS


class CollectionApproval(models.Model):
    """VIP approval request (BR-16, FR-23). Nothing is sent until the request
    is approved; then the email is sent or the stage recorded, and the
    approver is logged. Never deleted (Appendix C)."""
    _name = 'collection.approval'
    _description = 'Collection Approval Request'
    _inherit = ['mail.thread']
    _order = 'request_date desc, id desc'

    partner_id = fields.Many2one('res.partner', string="Customer", required=True, index=True)
    pipeline_id = fields.Many2one('collection.pipeline', required=True)
    stage_id = fields.Many2one('collection.stage', string="Requested stage", required=True)
    channel = fields.Selection(CHANNELS, string="Channel", required=True, default='email')
    template_id = fields.Many2one('mail.template', string="Email template")
    subject = fields.Char(string="Email subject")
    body = fields.Html(string="Email", sanitize_style=True)
    note = fields.Text(string="Note")
    requested_by = fields.Many2one(
        'res.users', default=lambda self: self.env.user, required=True, readonly=True)
    request_date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    state = fields.Selection([
        ('pending', 'Awaiting approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='pending', required=True, tracking=True)
    approved_as = fields.Selection(
        [('owner', 'Approved by owner'), ('manager', 'Approved by manager')], tracking=True)
    decided_by = fields.Many2one('res.users', string="Recorded by", readonly=True, tracking=True)
    decision_date = fields.Datetime(readonly=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    def unlink(self):
        raise UserError(_("Approval requests are kept for the audit trail and cannot be deleted."))

    def _check_can_decide(self):
        # Appendix B: the accountant records the approval, the manager approves
        if not self.env.user.has_group('collections_workbench.group_collection_accountant'):
            raise AccessError(_("Only the accountant or the manager can record an approval."))
        if self.filtered(lambda r: r.state != 'pending'):
            raise UserError(_("This request has already been decided."))

    def _approve(self, how):
        self._check_can_decide()
        for request in self:
            request.write({
                'state': 'approved',
                'approved_as': how,
                'decided_by': self.env.user.id,
                'decision_date': fields.Datetime.now(),
            })
            request.partner_id.with_context(collection_approved=True)._collection_apply_stage(
                request.stage_id, channel=request.channel, note=request.note,
                subject=request.subject, body=request.body, approval=request)
        return True

    def action_approve_owner(self):
        return self._approve('owner')

    def action_approve_manager(self):
        return self._approve('manager')

    def action_reject(self):
        self._check_can_decide()
        for request in self:
            request.write({
                'state': 'rejected',
                'decided_by': self.env.user.id,
                'decision_date': fields.Datetime.now(),
            })
            request.partner_id._collection_log('note_cat_system', _(
                'Approval rejected by %(user)s: stage "%(stage)s"',
                user=self.env.user.name, stage=request.stage_id.name), stage=request.stage_id)
        return True
