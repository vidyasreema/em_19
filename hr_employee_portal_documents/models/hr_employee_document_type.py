from odoo import fields, models

ASK_MODES = [('no', "Not asked"), ('optional', "Optional"), ('required', "Required")]

# Employee fields filled by the default types, by XML id: (number, expiry, file).
# The first field of each list that exists in the database is used, so a Studio
# field wins over Odoo's standard one, as in the portal's document alerts.
DEFAULT_FIELDS = {
    'doc_type_passport': (['passport_id'], ['x_studio_passport_expiration_date', 'passport_expiration_date'],
                          ['x_studio_passport_file']),
    'doc_type_visa': (['visa_no'], ['visa_expire'], ['x_studio_visa_file']),
    'doc_type_emirates_id': (['identification_id'], ['x_studio_id_expiration_date'], ['x_studio_id_file']),
    'doc_type_work_permit': (['permit_no'], ['x_studio_work_permit_expiration_date', 'work_permit_expiration_date'],
                             ['has_work_permit']),
    'doc_type_health_insurance': ([], ['x_studio_health_insurance_expiration_date'],
                                  ['x_studio_health_insurance_file']),
    'doc_type_photo': ([], [], ['x_studio_personal_photo']),
}


class HrEmployeeDocumentType(models.Model):
    _name = 'hr.employee.document.type'
    _description = "Employee portal document type"
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Char(
        "Hint for the employee", translate=True, help="Shown under the document name, e.g. 'Front and back'.")
    required = fields.Boolean(
        "Required", help="Every employee is asked to upload it until it is on file.")
    number_mode = fields.Selection(ASK_MODES, "Document number", default='no', required=True)
    expiry_mode = fields.Selection(ASK_MODES, "Expiry date", default='no', required=True)
    number_field_id = fields.Many2one(
        'ir.model.fields', "Number goes to", ondelete='set null',
        domain="[('model', '=', 'hr.employee'), ('ttype', '=', 'char'), ('store', '=', True)]",
        help="Employee field that receives the document number when HR verifies an upload.")
    expiry_field_id = fields.Many2one(
        'ir.model.fields', "Expiry goes to", ondelete='set null',
        domain="[('model', '=', 'hr.employee'), ('ttype', '=', 'date'), ('store', '=', True)]",
        help="Employee field that receives the expiry date when HR verifies an upload.")
    file_field_id = fields.Many2one(
        'ir.model.fields', "File goes to", ondelete='set null',
        domain="[('model', '=', 'hr.employee'), ('ttype', '=', 'binary')]",
        help="Employee file field that receives the first uploaded file when HR verifies an upload.")

    def _ep_link_default_fields(self):
        """Point the default types at the employee fields of this database."""
        Fields = self.env['ir.model.fields']
        for xmlid, candidate_lists in DEFAULT_FIELDS.items():
            doc_type = self.env.ref('hr_employee_portal_documents.%s' % xmlid, raise_if_not_found=False)
            if not doc_type:
                continue
            vals = {}
            for target, candidates in zip(('number_field_id', 'expiry_field_id', 'file_field_id'), candidate_lists):
                if doc_type[target]:
                    continue
                for fname in candidates:
                    field = Fields._get('hr.employee', fname)
                    if field:
                        vals[target] = field.id
                        break
            if vals:
                doc_type.write(vals)
