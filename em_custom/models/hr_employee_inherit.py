from odoo import fields, models

class HrEmployeeInherit(models.Model):
    _inherit = 'hr.employee'

    work_contract = fields.Binary('Work Contract')