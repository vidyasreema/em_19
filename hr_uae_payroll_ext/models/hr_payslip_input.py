from odoo import fields, models


class HrPayslipInput(models.Model):
    _inherit = 'hr.payslip.input'

    # Set on the input lines this module adds from approved records; they are
    # replaced each time the payslip is computed.
    uae_adjustment_id = fields.Many2one('hr.payroll.adjustment', string="Addition/Deduction",
                                        index='btree_not_null', ondelete='set null', readonly=True)
    uae_loan_id = fields.Many2one('hr.employee.loan', string="Loan",
                                  index='btree_not_null', ondelete='set null', readonly=True)
