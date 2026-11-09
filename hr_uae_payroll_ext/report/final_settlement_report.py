from odoo import api, models


class ReportFinalSettlement(models.AbstractModel):
    _name = 'report.hr_uae_payroll_ext.report_final_settlement'
    _description = 'Final Settlement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['hr.end.of.service'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'hr.end.of.service',
            'docs': docs,
            'gratuity': {doc.id: doc.employee_id._uae_gratuity(doc.last_working_day) for doc in docs},
            'leave': {doc.id: doc.employee_id._uae_annual_leave_settlement(doc.last_working_day) for doc in docs},
        }
