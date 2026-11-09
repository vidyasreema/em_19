from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    uae_notice_days = fields.Integer(related='company_id.uae_notice_days', readonly=False)
    uae_fine_max_days = fields.Float(related='company_id.uae_fine_max_days', readonly=False)
    uae_loan_max_salary_months = fields.Float(related='company_id.uae_loan_max_salary_months', readonly=False)
    uae_loan_max_installments = fields.Integer(related='company_id.uae_loan_max_installments', readonly=False)
    uae_loan_deduction_cap = fields.Float(related='company_id.uae_loan_deduction_cap', readonly=False)
