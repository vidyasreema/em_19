from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .hr_payroll_adjustment import PAYROLL_MANAGER_GROUP, payroll_approvers

DEPARTURE_REASONS = {
    'resignation': 'hr.departure_resigned',
    'termination': 'hr.departure_fired',
    'retirement': 'hr.departure_retired',
}


class HrEndOfService(models.Model):
    """An employee leaving: resignation, termination or end of contract.

    Workflow: draft -> to approve -> approved (the contract now ends on the last
    working day) -> final settlement (the payslip of the last month, with
    gratuity, leave balance, notice pay and loan recovery) -> done (the
    employee is archived once that payslip is validated).
    """
    _name = 'hr.end.of.service'
    _description = 'End of Service'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'last_working_day desc, id desc'
    _check_company_auto = True

    name = fields.Char(string="Reference", readonly=True, copy=False, default=lambda self: self.env._("New"))
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True, index=True,
                                  tracking=True, check_company=True, context={'active_test': False})
    company_id = fields.Many2one('res.company', string="Company", required=True, readonly=True,
                                 compute='_compute_company_id', store=True, precompute=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    reason = fields.Selection([
        ('resignation', "Resignation"),
        ('termination', "Termination"),
        ('contract_end', "End of Contract (not renewed)"),
        ('retirement', "Retirement"),
        ('other', "Other"),
    ], string="Reason", required=True, default='resignation', tracking=True)
    description = fields.Text(string="Details")
    notice_date = fields.Date(string="Notice Date", required=True, default=fields.Date.context_today, tracking=True,
                              help="Day the resignation or termination notice was given.")
    notice_days = fields.Integer(
        string="Notice Period (days)", required=True, tracking=True,
        default=lambda self: self.env.company.uae_notice_days)
    last_working_day = fields.Date(
        string="Last Working Day", required=True, tracking=True,
        compute='_compute_last_working_day', store=True, readonly=False, precompute=True)
    notice_pay = fields.Selection([
        ('none', "Notice period worked"),
        ('pay', "Company pays the notice in lieu"),
        ('deduct', "Employee pays the notice in lieu"),
    ], string="Notice Not Worked", required=True, default='none', tracking=True)
    notice_pay_days = fields.Float(
        string="Days in Lieu", compute='_compute_notice_pay_days', store=True, readonly=False,
        help="Notice days not worked, paid at gross salary / 30 per day.")
    state = fields.Selection([
        ('draft', "Draft"),
        ('to_approve', "To Approve"),
        ('approved', "Approved"),
        ('settlement', "Final Settlement"),
        ('done', "Done"),
        ('cancel', "Cancelled"),
    ], string="Status", default='draft', required=True, readonly=True, copy=False, tracking=True)
    payslip_id = fields.Many2one('hr.payslip', string="Final Settlement Payslip", readonly=True, copy=False)
    payslip_state = fields.Selection(related='payslip_id.state', string="Payslip Status")
    contract_end_before = fields.Date(readonly=True, copy=False,
                                      help="Contract end date before this end of service, restored if it is cancelled.")

    # Estimates on the last working day, for the form and the report.
    gratuity_amount = fields.Monetary(string="Gratuity", compute='_compute_estimates')
    service_years = fields.Float(string="Service (years)", compute='_compute_estimates', digits=(16, 2))
    unpaid_days = fields.Float(string="Unpaid Days Excluded", compute='_compute_estimates')
    leave_days = fields.Float(string="Annual Leave to Settle (days)", compute='_compute_estimates', digits=(16, 2),
                              help="Positive: paid to the employee. Negative: more taken than earned, deducted.")
    leave_amount = fields.Monetary(string="Annual Leave Settlement", compute='_compute_estimates')
    notice_amount = fields.Monetary(string="Notice in Lieu", compute='_compute_estimates')
    loan_amount = fields.Monetary(string="Outstanding Loans", compute='_compute_estimates')
    net_amount = fields.Monetary(string="Final Settlement (net)", compute='_compute_estimates',
                                 help="Net pay of the final settlement payslip once computed.")

    @api.depends('employee_id')
    def _compute_company_id(self):
        for record in self:
            record.company_id = record.employee_id.company_id or self.env.company

    @api.depends('notice_date', 'notice_days')
    def _compute_last_working_day(self):
        for record in self:
            if record.notice_date:
                record.last_working_day = record.notice_date + relativedelta(days=max(record.notice_days - 1, 0))

    @api.depends('notice_pay', 'notice_date', 'notice_days', 'last_working_day')
    def _compute_notice_pay_days(self):
        """Notice days after the last working day: the part of the notice not worked."""
        for record in self:
            if record.notice_pay == 'none' or not record.notice_date or not record.last_working_day:
                record.notice_pay_days = 0
                continue
            notice_end = record.notice_date + relativedelta(days=max(record.notice_days - 1, 0))
            record.notice_pay_days = max(0, (notice_end - record.last_working_day).days)

    @api.depends('employee_id', 'last_working_day', 'notice_pay', 'notice_pay_days', 'payslip_id.net_wage')
    def _compute_estimates(self):
        for record in self:
            if not record.employee_id or not record.last_working_day:
                record.update({
                    'gratuity_amount': 0, 'service_years': 0, 'unpaid_days': 0, 'leave_days': 0,
                    'leave_amount': 0, 'notice_amount': 0, 'loan_amount': 0, 'net_amount': 0,
                })
                continue
            gratuity = record.employee_id._uae_gratuity(record.last_working_day)
            leave = record.employee_id._uae_annual_leave_settlement(record.last_working_day)
            loans = self.env['hr.employee.loan'].search([
                ('employee_id', '=', record.employee_id.id), ('state', '=', 'running')])
            record.update({
                'gratuity_amount': gratuity['amount'],
                'service_years': gratuity['years'],
                'unpaid_days': gratuity['unpaid_days'],
                'leave_days': leave['days'],
                'leave_amount': leave['amount'],
                'notice_amount': record._uae_notice_amount(),
                'loan_amount': sum(loans.mapped('remaining_amount')),
                'net_amount': record.payslip_id.net_wage,
            })

    def _uae_notice_amount(self):
        """Pay in lieu of notice: gross salary / 30 per day, positive when the
        company pays it, negative when the employee owes it."""
        self.ensure_one()
        if self.notice_pay == 'none' or not self.notice_pay_days:
            return 0.0
        employee = self.employee_id.sudo()
        version = employee._get_version(self.last_working_day) or employee.version_id
        divisor = self.env['hr.rule.parameter']._get_parameter_from_code(
            'l10n_ae_ext_leave_day_divisor', self.last_working_day)
        amount = self.currency_id.round(self.notice_pay_days * version.l10n_ae_total_salary / divisor)
        return amount if self.notice_pay == 'pay' else -amount

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._("New")) == self.env._("New"):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.end.of.service') or self.env._("New")
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_if_draft(self):
        if any(record.state not in ('draft', 'cancel') for record in self):
            raise UserError(self.env._("Only draft or cancelled records can be deleted."))

    def _check_manager(self):
        if not self.env.user.has_group(PAYROLL_MANAGER_GROUP):
            raise UserError(self.env._("Only a Payroll Manager can approve."))

    def _version(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        return employee._get_version(self.last_working_day) or employee.version_id

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def action_submit(self):
        for record in self.filtered(lambda r: r.state == 'draft'):
            record.state = 'to_approve'
            for user in payroll_approvers(self.env, record.company_id):
                record.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                         summary=self.env._("Approve %s", record.name))

    def action_approve(self):
        """The contract now ends on the last working day."""
        self._check_manager()
        for record in self.filtered(lambda r: r.state in ('draft', 'to_approve')):
            version = record._version()
            if version.contract_date_start and version.contract_date_start > record.last_working_day:
                raise UserError(self.env._("The last working day is before the start of the current contract."))
            record.contract_end_before = version.contract_date_end
            version.contract_date_end = record.last_working_day
            record.state = 'approved'
        self.activity_feedback(['mail.mail_activity_data_todo'])

    def action_create_settlement(self):
        """The final settlement is the UAE monthly payslip of the month of the
        last working day: an existing draft one is used, so the employee is not
        paid twice for that month."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(self.env._("Approve the end of service first."))
        structure = self.env.ref('hr_uae_payroll_ext.structure_uae_monthly')
        date_from = self.last_working_day.replace(day=1)
        date_to = date_from + relativedelta(months=1, days=-1)
        Payslip = self.env['hr.payslip']
        slips = Payslip.search([
            ('employee_id', '=', self.employee_id.id),
            ('struct_id', '=', structure.id),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_from),
            ('state', '!=', 'cancel'),
        ])
        if slips.filtered(lambda s: s.state != 'draft'):
            raise UserError(self.env._(
                "The payslip of %(month)s is already validated. Cancel it first, the final settlement "
                "replaces it.", month=date_from.strftime('%B %Y')))
        payslip = slips[:1]
        if payslip:
            payslip.uae_end_of_service_id = self
        else:
            payslip = Payslip.create({
                'name': self.env._("Final Settlement - %s", self.employee_id.name),
                'employee_id': self.employee_id.id,
                'version_id': self._version().id,
                'struct_id': structure.id,
                'date_from': date_from,
                'date_to': date_to,
                'uae_end_of_service_id': self.id,
            })
        payslip.compute_sheet()
        self.write({'payslip_id': payslip.id, 'state': 'settlement'})
        return self.action_open_payslip()

    def action_open_payslip(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'res_id': self.payslip_id.id,
            'view_mode': 'form',
        }

    def action_done(self):
        """Archive the employee once the final settlement is validated. The
        portal user is kept, so the employee can still see the settlement."""
        self._check_manager()
        for record in self:
            if record.payslip_id.state not in ('validated', 'paid'):
                raise UserError(self.env._("Validate the final settlement payslip first."))
            employee = record.employee_id
            reason = DEPARTURE_REASONS.get(record.reason)
            employee.write({
                'departure_date': record.last_working_day,
                'departure_reason_id': self.env.ref(reason).id if reason else employee.departure_reason_id.id,
                'departure_description': record.description or False,
            })
            if employee.active:
                employee.with_context(no_wizard=True).action_archive()
            record.state = 'done'

    def action_cancel(self):
        """Back to the original contract end; the settlement payslip, if not
        validated, becomes a normal payslip again."""
        for record in self:
            if record.state == 'done' or record.payslip_id.state in ('validated', 'paid'):
                raise UserError(self.env._("The final settlement is already validated."))
            if record.state in ('approved', 'settlement'):
                record._version().contract_date_end = record.contract_end_before
            if record.payslip_id:
                record.payslip_id.uae_end_of_service_id = False
            record.write({'state': 'cancel', 'payslip_id': False})
        self.activity_unlink(['mail.mail_activity_data_todo'])

    def action_draft(self):
        self.filtered(lambda r: r.state == 'cancel').state = 'draft'

    def action_print(self):
        return self.env.ref('hr_uae_payroll_ext.action_report_final_settlement').report_action(self)
