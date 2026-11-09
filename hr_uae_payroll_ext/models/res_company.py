from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    uae_notice_days = fields.Integer(string="Notice Period (days)", default=30,
                                     help="Default notice period of a resignation or termination.")
    uae_fine_max_days = fields.Float(string="Fine Limit (days of salary)", default=5,
                                     help="Warn when the fines of a month exceed this many days of gross salary. 0: no warning.")
    uae_loan_max_salary_months = fields.Float(string="Maximum Loan (months of salary)", default=2,
                                              help="0: no limit.")
    uae_loan_max_installments = fields.Integer(string="Maximum Instalments", default=12,
                                               help="0: no limit.")
    uae_loan_deduction_cap = fields.Float(string="Loan Deduction Cap (%)", default=20,
                                          help="Loan instalments deducted from one payslip are at most this "
                                               "percentage of the gross salary. 0: no cap.")
