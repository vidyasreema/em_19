from odoo import fields, models
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    ep_document_to_check_count = fields.Integer(compute='_compute_ep_document_to_check_count',
                                                groups='hr.group_hr_user')

    def _compute_ep_document_to_check_count(self):
        counts = dict(self.env['hr.employee.document']._read_group(
            [('employee_id', 'in', self.ids), ('state', '=', 'pending')], ['employee_id'], ['__count']))
        for employee in self:
            employee.ep_document_to_check_count = counts.get(employee, 0)

    def action_ep_open_documents(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_employee_portal_documents.hr_employee_document_action')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def _ep_document_types(self):
        return self.env['hr.employee.document.type'].sudo().search([])

    def _ep_document_on_file(self, doc_type):
        """What the profile already holds for `doc_type`: (on file, number, expiry date)."""
        self.ensure_one()
        employee = self.sudo()
        number = employee[doc_type.number_field_id.name] if doc_type.number_field_id else False
        expiry = employee[doc_type.expiry_field_id.name] if doc_type.expiry_field_id else False
        has_file = bool(doc_type.file_field_id and employee[doc_type.file_field_id.name])
        return bool(number or expiry or has_file), number, expiry

    def _ep_document_checklist(self):
        """One line per document type: its status for this employee.

        status: 'pending' (waiting for HR), 'rejected' (to upload again), 'on_file'
        (verified, or entered by HR) or 'missing'."""
        self.ensure_one()
        uploads = self.env['hr.employee.document'].sudo().search(
            [('employee_id', '=', self.id), ('state', '!=', 'cancel')])
        lines = []
        for doc_type in self._ep_document_types():
            latest = uploads.filtered(lambda d: d.type_id == doc_type)[:1]
            on_file, number, expiry = self._ep_document_on_file(doc_type)
            if latest.state == 'verified':
                on_file = True
                number = number or latest.document_number
                expiry = expiry or latest.expiry_date
            if latest.state in ('pending', 'rejected'):
                status = latest.state
            else:
                status = 'on_file' if on_file else 'missing'
            lines.append({
                'type': doc_type,
                'status': status,
                'upload': latest,
                'number': number,
                'expiry': expiry,
            })
        return lines

    def _ep_documents_to_upload(self):
        """Required documents still missing, or rejected by HR."""
        return [line for line in self._ep_document_checklist()
                if line['status'] == 'rejected' or (line['status'] == 'missing' and line['type'].required)]

    def _ep_upload_document(self, doc_type, number='', expiry=None, note='', files=()):
        """Send a document to HR. A newer upload of the same type replaces one still waiting."""
        self.ensure_one()
        if doc_type not in self._ep_document_types():
            raise UserError(self.env._("This document cannot be uploaded from the portal."))
        number = (number or '').strip()
        missing = []
        if doc_type.number_mode == 'required' and not number:
            missing.append(self.env._("document number"))
        if doc_type.expiry_mode == 'required' and not expiry:
            missing.append(self.env._("expiry date"))
        attachment_values = self._ep_prepare_attachments(files)
        if not attachment_values:
            missing.append(self.env._("file"))
        if missing:
            raise UserError(self.env._("Please fill in: %s.", ', '.join(missing)))
        if expiry and expiry < fields.Date.context_today(self):
            raise UserError(self.env._("This document has expired. Please upload the renewed one."))

        Document = self.env['hr.employee.document'].sudo()
        Document.search([('employee_id', '=', self.id), ('type_id', '=', doc_type.id),
                         ('state', '=', 'pending')]).write({'state': 'cancel'})
        document = Document.create({
            'employee_id': self.id,
            'type_id': doc_type.id,
            'document_number': number if doc_type.number_mode != 'no' else False,
            'expiry_date': expiry if doc_type.expiry_mode != 'no' else False,
            'employee_note': (note or '').strip() or False,
        })
        attachments = self.env['ir.attachment'].sudo().create([
            dict(vals, res_model='hr.employee.document', res_id=document.id) for vals in attachment_values
        ])
        document.attachment_ids = attachments
        return document
