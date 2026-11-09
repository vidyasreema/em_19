from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import plaintext2html

# Requests an employee can still cancel and HR can still decide.
OPEN_REQUEST_STATES = ('new', 'pending')


class ApprovalRequest(models.Model):
    _inherit = 'approval.request'

    ep_employee_id = fields.Many2one(
        'hr.employee', "Employee", compute='_compute_ep_employee_id', store=True, readonly=False, index='btree_not_null')
    ep_hr_note = fields.Text("Note to the employee", help="Shown to the employee on their portal.")

    @api.depends('request_owner_id')
    def _compute_ep_employee_id(self):
        for approval in self:
            if approval.ep_employee_id.user_id == approval.request_owner_id:
                continue
            approval.ep_employee_id = self.env['hr.employee'].sudo().search([
                ('user_id', '=', approval.request_owner_id.id),
                ('company_id', 'in', [approval.company_id.id or self.env.company.id]),
            ], limit=1) if approval.request_owner_id else False

    def _ep_reply_attachments(self):
        """Documents added by HR, such as the certificate asked for."""
        self.ensure_one()
        return self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'approval.request'), ('res_id', '=', self.id), ('res_field', '=', False),
            ('create_uid', '!=', self.request_owner_id.id),
        ], order='id')

    def _ep_own_attachments(self):
        self.ensure_one()
        return self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'approval.request'), ('res_id', '=', self.id), ('res_field', '=', False),
            ('create_uid', '=', self.request_owner_id.id),
        ], order='id')

    def _ep_portal_decide(self, decision, user, note='', attachment_values=()):
        """Approve or refuse from the portal HR dashboard, for every approver
        at once, as an Approval Officer would force it in the backend."""
        self.ensure_one()
        if self.request_status not in OPEN_REQUEST_STATES:
            raise UserError(self.env._("This request was already approved, refused or cancelled."))
        if self.request_owner_id == user:
            raise UserError(self.env._("You cannot approve or refuse your own request."))
        if decision not in ('approve', 'refuse'):
            raise UserError(self.env._("Unknown decision."))
        if not self.approver_ids:
            self.approver_ids = [fields.Command.create({'user_id': user.id, 'status': 'pending'})]
        open_approvers = self.approver_ids.filtered(lambda a: a.status not in ('approved', 'refused', 'cancel'))
        if decision == 'approve':
            open_approvers.write({'status': 'approved'})
            body = self.env._("Approved by %s from the employee portal.", user.name)
        else:
            (open_approvers or self.approver_ids).write({'status': 'refused'})
            body = self.env._("Refused by %s from the employee portal.", user.name)
        self._cancel_activities()
        note = (note or '').strip()
        if note:
            self.ep_hr_note = note
        if attachment_values:
            self.env['ir.attachment'].create([
                dict(vals, res_model='approval.request', res_id=self.id) for vals in attachment_values
            ])
        self.message_post(body=plaintext2html('%s\n%s' % (body, note) if note else body),
                          author_id=user.partner_id.id, subtype_xmlid='mail.mt_note')
