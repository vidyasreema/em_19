from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    barcode_expected_type = fields.Selection([
        ('gs1', 'GS1'),
        ('template', 'Reading Template'),
        ('manual', 'Manual'),
    ], string='Expected Barcode Type', help="Hint shown to the employee at receipt. It does not decide how a carton is read.")
    barcode_scan_requirement = fields.Selection([
        ('none', 'None'),
        ('warning', 'Warning'),
        ('required', 'Required'),
    ], string='Carton Scan Requirement', default='none', required=True,
        help="None: no message.\n"
             "Warning: the receipt is posted with a message that some lines have no carton details.\n"
             "Required: Validate is rejected for any line without carton details "
             "(a carton without a barcode passes with a generated barcode).")
