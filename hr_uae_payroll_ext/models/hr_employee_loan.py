from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .hr_payroll_adjustment import PAYROLL_MANAGER_GROUP, payroll_approvers

PAID_PAYSLIP_STATES = ('validated', 'paid')


class HrEmployeeLoan(models.Model):
    """A loan or salary advance, paid out to the employee outside payroll and
    recovered from the payslips: each payslip deducts the instalments due by
    its end date that are not recovered yet, up to the deduction cap of the
    company. What is left is recovered in the final settlement."""
    _name = 'hr.employee.loan'
    _description = 'Employee Loan or Salary Advance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string="Reference", readonly=True, copy=False, default=lambda self: self.env._("New"))
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True, index=True,
                                  tracking=True, check_company=True)
    company_id = fields.Many2one('res.company', string="Company", required=True, readonly=True,
                                 compute='_compute_company_id', store=True, precompute=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    loan_type = fields.Selection([
        ('loan', "Loan"),
        ('advance', "Salary Advance"),
    ], string="Type", required=True, default='loan', tracking=True)
    amount = fields.Monetary(string="Amount", required=True, tracking=True)
    installment_count = fields.Integer(
        string="Number of Instalments", required=True, default=1, tracking=True,
        compute='_compute_installment_count', store=True, readonly=False, precompute=True,
        help="Monthly deductions. A salary advance is recovered in one go.")
    installment_amount = fields.Monetary(string="Monthly Instalment", compute='_compute_installment_amount')
    date = fields.Date(string="Request Date", required=True, default=fields.Date.context_today)
    first_deduction_date = fields.Date(
        string="First Deduction", required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self) + relativedelta(months=1, day=1),
        help="Month of the first instalment.")
    reason = fields.Text(string="Reason", required=True)
    state = fields.Selection([
        ('draft', "Draft"),
        ('to_approve', "To Approve"),
        ('running', "Running"),
        ('closed', "Paid Off"),
        ('refused', "Refused"),
    ], string="Status", default='draft', required=True, readonly=True, copy=False, tracking=True)
    line_ids = fields.One2many('hr.employee.loan.line', 'loan_id', string="Instalments", copy=False)
    input_line_ids = fields.One2many('hr.payslip.input', 'uae_loan_id', string="Payslip Deductions", readonly=True)
    paid_amount = fields.Monetary(string="Recovered", compute='_compute_amounts', store=True)
    remaining_amount = fields.Monetary(string="Outstanding", compute='_compute_amounts', store=True, tracking=True)
    limit_warning = fields.Char(compute='_compute_limit_warning')

    _positive_amount = models.Constraint('CHECK(amount > 0)', "The amount must be positive.")
    _positive_installments = models.Constraint('CHECK(installment_count > 0)', "There must be at least one instalment.")

    @api.depends('employee_id')
    def _compute_company_id(self):
        for loan in self:
            loan.company_id = loan.employee_id.company_id or self.env.company

    @api.depends('loan_type')
    def _compute_installment_count(self):
        for loan in self:
            if loan.loan_type == 'advance' or not loan.installment_count:
                loan.installment_count = 1

    @api.depends('amount', 'installment_count')
    def _compute_installment_amount(self):
        for loan in self:
            loan.installment_amount = loan.currency_id.round(loan.amount / loan.installment_count) if loan.installment_count else 0

    @api.depends('amount', 'input_line_ids.amount', 'input_line_ids.payslip_id.state')
    def _compute_amounts(self):
        for loan in self:
            loan.paid_amount = sum(loan.input_line_ids.filtered(
                lambda line: line.payslip_id.state in PAID_PAYSLIP_STATES).mapped('amount'))
            loan.remaining_amount = loan.amount - loan.paid_amount

    @api.depends('amount', 'installment_count', 'employee_id')
    def _compute_limit_warning(self):
        for loan in self:
            loan.limit_warning = '; '.join(loan._uae_limit_errors())

    def _uae_limit_errors(self):
        """Company limits this loan exceeds (Payroll settings)."""
        self.ensure_one()
        errors = []
        company = self.company_id
        gross = self.employee_id.sudo().version_id.l10n_ae_total_salary
        if company.uae_loan_max_salary_months and gross and self.amount > gross * company.uae_loan_max_salary_months:
            errors.append(self.env._("more than %(months)s months of salary (%(max)s)",
                                     months=company.uae_loan_max_salary_months,
                                     max=self.currency_id.format(gross * company.uae_loan_max_salary_months)))
        if company.uae_loan_max_installments and self.installment_count > company.uae_loan_max_installments:
            errors.append(self.env._("more than %s instalments", company.uae_loan_max_installments))
        return errors

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._("New")) == self.env._("New"):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.employee.loan') or self.env._("New")
            if vals.get('loan_type') == 'advance':
                vals['installment_count'] = 1
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('loan_type') == 'advance':
            vals = dict(vals, installment_count=1)
        result = super().write(vals)
        if 'installment_count' in vals and self.filtered(lambda l: l.loan_type == 'advance' and l.installment_count != 1):
            raise ValidationError(self.env._("A salary advance is recovered in one instalment."))
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_if_draft(self):
        if any(loan.state not in ('draft', 'refused') for loan in self):
            raise UserError(self.env._("Only draft or refused loans can be deleted."))

    def _check_manager(self):
        if not self.env.user.has_group(PAYROLL_MANAGER_GROUP):
            raise UserError(self.env._("Only a Payroll Manager can approve or refuse."))

    def action_compute_schedule(self):
        """Equal monthly instalments from the first deduction month; the last one
        takes the rounding difference."""
        for loan in self:
            if loan.state not in ('draft', 'to_approve'):
                raise UserError(self.env._("The schedule of an approved loan can only be edited line by line."))
            count = loan.installment_count
            installment = loan.currency_id.round(loan.amount / count)
            first = loan.first_deduction_date.replace(day=1)
            loan.line_ids = [fields.Command.clear()] + [fields.Command.create({
                'date': first + relativedelta(months=i),
                'amount': installment if i < count - 1 else loan.amount - installment * (count - 1),
            }) for i in range(count)]

    def action_submit(self):
        for loan in self.filtered(lambda l: l.state == 'draft'):
            if errors := loan._uae_limit_errors():
                raise UserError(self.env._("%(loan)s is above the company limits: %(errors)s.",
                                           loan=loan.name, errors='; '.join(errors)))
            if not loan.line_ids:
                loan.action_compute_schedule()
            loan.state = 'to_approve'
            for user in payroll_approvers(self.env, loan.company_id):
                loan.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                       summary=self.env._("Approve %s", loan.name))

    def action_approve(self):
        """Approve: a manager may approve above the limits (they are a warning then)."""
        self._check_manager()
        for loan in self.filtered(lambda l: l.state in ('draft', 'to_approve')):
            if not loan.line_ids:
                loan.action_compute_schedule()
            loan._check_schedule()
            loan.state = 'running'
        self.activity_feedback(['mail.mail_activity_data_todo'])

    def action_refuse(self):
        self._check_manager()
        if self.filtered(lambda l: l.paid_amount):
            raise UserError(self.env._("Part of this loan is already recovered from payslips."))
        self.state = 'refused'
        self.activity_unlink(['mail.mail_activity_data_todo'])

    def action_draft(self):
        if self.filtered(lambda l: l.paid_amount):
            raise UserError(self.env._("Part of this loan is already recovered from payslips."))
        self.state = 'draft'

    def _check_schedule(self):
        for loan in self:
            if loan.currency_id.compare_amounts(sum(loan.line_ids.mapped('amount')), loan.amount):
                raise ValidationError(self.env._(
                    "%(loan)s: the instalments add up to %(total)s, not %(amount)s.",
                    loan=loan.name, total=loan.currency_id.format(sum(loan.line_ids.mapped('amount'))),
                    amount=loan.currency_id.format(loan.amount)))

    def _uae_update_state(self):
        """Paid off when nothing is outstanding any more, running again otherwise."""
        for loan in self.filtered(lambda l: l.state in ('running', 'closed')):
            loan.state = 'closed' if loan.currency_id.is_zero(loan.remaining_amount) else 'running'

    def _uae_due_amount(self, payslip, final=False):
        """Instalments due by the end of `payslip` and not recovered yet by
        other validated payslips. Overdue instalments (cut by the cap) are
        included, so they are recovered as soon as possible. On the final
        settlement (`final`), the whole outstanding amount is due."""
        self.ensure_one()
        lines = self.line_ids if final else self.line_ids.filtered(lambda line: line.date <= payslip.date_to)
        scheduled = sum(lines.mapped('amount'))
        recovered = sum(self.input_line_ids.filtered(
            lambda line: line.payslip_id != payslip and line.payslip_id.state in PAID_PAYSLIP_STATES
        ).mapped('amount'))
        return max(0.0, min(scheduled, self.amount) - recovered)


class HrEmployeeLoanLine(models.Model):
    _name = 'hr.employee.loan.line'
    _description = 'Loan Instalment'
    _order = 'date, id'

    loan_id = fields.Many2one('hr.employee.loan', required=True, index=True, ondelete='cascade')
    currency_id = fields.Many2one(related='loan_id.currency_id')
    date = fields.Date(string="Month", required=True)
    amount = fields.Monetary(string="Amount", required=True)
    is_recovered = fields.Boolean(string="Recovered", compute='_compute_is_recovered')

    @api.depends('loan_id.paid_amount', 'loan_id.line_ids.amount', 'loan_id.line_ids.date')
    def _compute_is_recovered(self):
        """Recovered when the payslips cover this instalment and the ones before it."""
        for line in self:
            previous = line.loan_id.line_ids.filtered(lambda l: l.date <= line.date)
            line.is_recovered = line.loan_id.paid_amount >= sum(previous.mapped('amount')) - 0.001
