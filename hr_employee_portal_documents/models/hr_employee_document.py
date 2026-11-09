from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import plaintext2html

# Binary fields whose file name lives in a field not called <field>_filename.
FILENAME_FIELDS = {'has_work_permit': None}


class HrEmployeeDocument(models.Model):
    """A document an employee uploaded from the portal, waiting for HR or checked."""
    _name = 'hr.employee.document'
    _description = "Employee portal document"
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True, ondelete='cascade', tracking=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    type_id = fields.Many2one('hr.employee.document.type', "Document", required=True, ondelete='restrict',
                              tracking=True)
    document_number = fields.Char("Number", tracking=True)
    expiry_date = fields.Date("Expiry date", tracking=True)
    employee_note = fields.Char("Employee's note")
    attachment_ids = fields.Many2many('ir.attachment', string="Files")
    state = fields.Selection([
        ('pending', "To check"),
        ('verified', "Verified"),
        ('rejected', "Rejected"),
        ('cancel', "Replaced"),
    ], default='pending', required=True, tracking=True, index=True)
    hr_note = fields.Text("Note to the employee", help="Shown to the employee on their portal.")
    checked_by_id = fields.Many2one('res.users', "Checked by", readonly=True)
    checked_date = fields.Datetime("Checked on", readonly=True)

    @api.depends('employee_id.name', 'type_id.name')
    def _compute_name(self):
        for document in self:
            document.name = '%s - %s' % (document.employee_id.name or '', document.type_id.name or '')

    def _ep_files(self):
        """The uploaded files, first uploaded first."""
        return self.attachment_ids.sorted('id')

    def _ep_employee_values(self):
        """Values for the employee's fields, from this upload."""
        self.ensure_one()
        doc_type = self.type_id
        vals = {}
        if doc_type.number_field_id and self.document_number:
            vals[doc_type.number_field_id.name] = self.document_number
        if doc_type.expiry_field_id and self.expiry_date:
            vals[doc_type.expiry_field_id.name] = self.expiry_date
        files = self._ep_files()
        if doc_type.file_field_id and files:
            fname = doc_type.file_field_id.name
            vals[fname] = files[0].datas
            filename_field = FILENAME_FIELDS.get(fname, '%s_filename' % fname)
            if filename_field and filename_field in self.employee_id._fields:
                vals[filename_field] = files[0].name
        return vals

    def _ep_check_open(self):
        for document in self:
            if document.state != 'pending':
                raise UserError(self.env._("%s was already checked.", document.name))

    def action_verify(self):
        """Copy the file, number and expiry date into the employee's profile."""
        self._ep_check_open()
        for document in self:
            vals = document._ep_employee_values()
            if vals:
                document.employee_id.sudo().write(vals)
            document.write({'state': 'verified', 'checked_by_id': self.env.user.id,
                            'checked_date': fields.Datetime.now()})
            document.employee_id.sudo().message_post(
                body=self.env._("%(doc)s uploaded from the employee portal was verified by %(user)s.",
                                doc=document.type_id.name, user=self.env.user.name),
                subtype_xmlid='mail.mt_note')
        return True

    def action_reject(self):
        self._ep_check_open()
        if any(not (document.hr_note or '').strip() for document in self):
            raise UserError(self.env._(
                "Write a note to the employee first (tab 'Note to the employee'), so they know what to fix."))
        self.write({'state': 'rejected', 'checked_by_id': self.env.user.id, 'checked_date': fields.Datetime.now()})
        return True

    def _ep_portal_decide(self, decision, user, note=''):
        """Verify or reject from the portal HR dashboard."""
        self.ensure_one()
        if decision not in ('verify', 'reject'):
            raise UserError(self.env._("Unknown decision."))
        if self.employee_id.user_id == user:
            raise UserError(self.env._("You cannot check your own documents."))
        note = (note or '').strip()
        if decision == 'reject' and not (note or self.hr_note):
            raise UserError(self.env._("Write a note to the employee so they know what to fix."))
        if note:
            self.hr_note = note
        document = self.with_user(user).sudo()
        if decision == 'verify':
            document.action_verify()
            body = self.env._("Verified by %s from the employee portal.", user.name)
        else:
            document.action_reject()
            body = self.env._("Rejected by %s from the employee portal.", user.name)
        self.message_post(body=plaintext2html('%s\n%s' % (body, note) if note else body),
                          author_id=user.partner_id.id, subtype_xmlid='mail.mt_note')
