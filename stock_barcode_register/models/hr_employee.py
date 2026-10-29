from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    stock_operation_authorized = fields.Boolean(
        'Authorized for Operations',
        help="Appears in the Received by / Transferred by / Delivered by field of inventory operations.")


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    # Needed so users without HR rights can search authorized employees
    stock_operation_authorized = fields.Boolean(readonly=True)
