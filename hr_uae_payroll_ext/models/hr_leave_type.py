from odoo import api, fields, models

# Work entry codes the UAE structure pays at half or not at all.
UNPAID_WORK_ENTRY_CODES = ('LEAVE90', 'AESICKLEAVE0', 'SICKLEAVE0')
HALF_PAY_WORK_ENTRY_CODES = ('AESICKLEAVE50', 'SICKLEAVE50', 'AEHALFPAY')

# Standard UAE sick leave types: their work entry codes (SICKLEAVE50/0) are not the
# ones the UAE salary rules read (AESICKLEAVE50/0). Replaced by this module's types.
REPLACED_LEAVE_TYPES = (
    'hr_holidays.l10n_ae_leave_type_sick_leave_50',
    'hr_holidays.l10n_ae_leave_type_sick_leave_0',
)


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    uae_pay_rate = fields.Selection(
        [('100', "Full pay"), ('50', "Half pay"), ('0', "Unpaid")],
        string="Salary During Leave",
        compute='_compute_uae_pay_rate', store=True, readonly=False,
        help="Half pay and unpaid days are deducted from the payslip at gross salary / 30 per "
             "calendar day (UAE structure).")
    uae_count_calendar_days = fields.Boolean(
        string="Count Calendar Days",
        help="The duration counts every calendar day between the first and last day, "
             "weekends and public holidays included, as UAE labour law does for annual leave.")
    uae_days_per_contract = fields.Float(
        string="Days per Contract",
        help="Days given for each employment contract, at the contract start. A renewed "
             "contract gets the days again; unused days carry over. 0: not given per contract.")
    uae_min_service_months = fields.Integer(
        string="Available After (months)",
        help="Months of service needed before the employee can take this time off. "
             "0: no minimum.")

    @api.depends('work_entry_type_id')
    def _compute_uae_pay_rate(self):
        for leave_type in self:
            code = leave_type.work_entry_type_id.code
            if code in UNPAID_WORK_ENTRY_CODES:
                leave_type.uae_pay_rate = '0'
            elif code in HALF_PAY_WORK_ENTRY_CODES:
                leave_type.uae_pay_rate = '50'
            else:
                leave_type.uae_pay_rate = '100'

    @api.model
    def _uae_archive_unused_types(self):
        """Archive time off types nobody can use here: types of other countries,
        and the standard UAE sick types this module replaces. Types with requests
        or allocations are kept, so no history disappears from reports."""
        countries = self.env['res.company'].search([]).country_id
        own_type_ids = self.env['ir.model.data'].search([
            ('module', '=', 'hr_uae_payroll_ext'), ('model', '=', 'hr.leave.type'),
        ]).mapped('res_id')
        candidates = self.search([
            ('country_id', 'not in', [False] + countries.ids),
            ('id', 'not in', own_type_ids),
        ])
        for xmlid in REPLACED_LEAVE_TYPES:
            candidates |= self.env.ref(xmlid, raise_if_not_found=False) or self
        used_ids = set(self.env['hr.leave'].with_context(active_test=False).search(
            [('holiday_status_id', 'in', candidates.ids)]).holiday_status_id.ids)
        used_ids |= set(self.env['hr.leave.allocation'].with_context(active_test=False).search(
            [('holiday_status_id', 'in', candidates.ids)]).holiday_status_id.ids)
        candidates.filtered(lambda t: t.id not in used_ids).write({'active': False, 'ep_portal_available': False})
