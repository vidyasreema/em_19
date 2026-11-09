from odoo import api, fields, models
from odoo.exceptions import UserError

PAYROLL_MANAGER_GROUP = 'hr_payroll.group_hr_payroll_manager'


def payroll_approvers(env, company):
    """Payroll managers of `company`, who receive the approval activities."""
    return env.ref(PAYROLL_MANAGER_GROUP).sudo().all_user_ids.filtered(
        lambda user: not user.share and company in user.company_ids)


class HrPayrollAdjustment(models.Model):
    """A bonus, fine or other addition/deduction (see hr.payroll.adjustment.type) for one employee. Once
    approved, it is added to the employee's next payslip (the first one whose
    period ends on or after its date), and marked paid when that payslip is
    validated."""
    _name = 'hr.payroll.adjustment'
    _description = 'Payroll Addition or Deduction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string="Reference", readonly=True, copy=False, default=lambda self: self.env._("New"))
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True, index=True,
                                  tracking=True, check_company=True)
    company_id = fields.Many2one('res.company', string="Company", required=True, readonly=True,
                                 compute='_compute_company_id', store=True, precompute=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    type_id = fields.Many2one('hr.payroll.adjustment.type', string="Type", required=True, tracking=True,
                              ondelete='restrict', index=True)
    is_deduction = fields.Boolean(compute='_compute_is_deduction')
    amount = fields.Monetary(string="Amount", required=True, tracking=True)
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today, tracking=True,
                       help="Added to the payslip of this month, or to the next one if that month is already paid.")
    reason = fields.Text(string="Reason", required=True)
    state = fields.Selection([
        ('draft', "Draft"),
        ('to_approve', "To Approve"),
        ('approved', "Approved"),
        ('paid', "In Payslip"),
        ('refused', "Refused"),
    ], string="Status", default='draft', required=True, readonly=True, copy=False, tracking=True)
    payslip_id = fields.Many2one('hr.payslip', string="Payslip", readonly=True, copy=False)
    fine_warning = fields.Char(compute='_compute_fine_warning')

    _positive_amount = models.Constraint('CHECK(amount > 0)', "The amount must be positive.")

    @api.depends('employee_id')
    def _compute_company_id(self):
        for adjustment in self:
            adjustment.company_id = adjustment.employee_id.company_id or self.env.company

    @api.depends('type_id.kind')
    def _compute_is_deduction(self):
        for adjustment in self:
            adjustment.is_deduction = adjustment.type_id.kind == 'deduction'

    @api.depends('type_id.is_fine', 'amount', 'date', 'employee_id')
    def _compute_fine_warning(self):
        """UAE law: fines may not exceed 5 days' wage in a month (days set in Payroll settings)."""
        for adjustment in self:
            adjustment.fine_warning = False
            if not adjustment.type_id.is_fine or not adjustment.employee_id or not adjustment.date:
                continue
            max_days = adjustment.company_id.uae_fine_max_days
            gross = adjustment.employee_id.sudo().version_id.l10n_ae_total_salary
            if not max_days or not gross:
                continue
            month_start = adjustment.date.replace(day=1)
            others = self.search([
                ('employee_id', '=', adjustment.employee_id.id),
                ('type_id.is_fine', '=', True),
                ('state', 'not in', ('draft', 'refused')),
                ('date', '>=', month_start),
                ('date', '<', fields.Date.add(month_start, months=1)),
                ('id', '!=', adjustment._origin.id),
            ])
            total = sum(others.mapped('amount')) + adjustment.amount
            limit = gross / 30 * max_days
            if total > limit:
                adjustment.fine_warning = self.env._(
                    "Fines this month: %(total)s, more than %(days)s days of salary (%(limit)s).",
                    total=adjustment.currency_id.format(total), days=max_days,
                    limit=adjustment.currency_id.format(limit))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._("New")) == self.env._("New"):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.payroll.adjustment') or self.env._("New")
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_if_draft(self):
        if any(adjustment.state not in ('draft', 'refused') for adjustment in self):
            raise UserError(self.env._("Only draft or refused records can be deleted."))

    def _uae_input_type(self):
        self.ensure_one()
        return self.type_id.input_type_id

    def _check_manager(self):
        if not self.env.user.has_group(PAYROLL_MANAGER_GROUP):
            raise UserError(self.env._("Only a Payroll Manager can approve or refuse."))

    def action_submit(self):
        for record in self.filtered(lambda r: r.state == 'draft'):
            record.state = 'to_approve'
            for user in payroll_approvers(self.env, record.company_id):
                record.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                         summary=self.env._("Approve %s", record.name))

    def action_approve(self):
        self._check_manager()
        self.filtered(lambda r: r.state in ('draft', 'to_approve')).state = 'approved'
        self.activity_feedback(['mail.mail_activity_data_todo'])

    def action_refuse(self):
        self._check_manager()
        if self.filtered(lambda r: r.state == 'paid'):
            raise UserError(self.env._("This is already in a validated payslip."))
        self.state = 'refused'
        self.activity_unlink(['mail.mail_activity_data_todo'])

    def action_draft(self):
        if self.filtered(lambda r: r.state == 'paid'):
            raise UserError(self.env._("This is already in a validated payslip."))
        self.state = 'draft'
