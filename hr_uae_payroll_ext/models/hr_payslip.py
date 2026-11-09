from odoo import Command, fields, models

# Pay rate of a time off type -> share of the daily salary deducted.
DEDUCTION_SHARE = {'0': 1.0, '50': 0.5}
# Leave deduction rules -> their pay rate, for the days shown on the printed payslip.
LEAVE_RULE_RATES = {'UAEUNPAID': '0', 'UAEHALFPAY': '50'}
# Totals the printed payslip shows on its own, not as earnings or deductions.
REPORT_TOTAL_CODES = {'GROSS', 'NET', 'NETCOST', 'AE_NETCOST'}


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    uae_end_of_service_id = fields.Many2one(
        'hr.end.of.service', string="End of Service", readonly=True, copy=False, index='btree_not_null',
        help="Set on the final settlement payslip: it adds the gratuity, the annual leave "
             "balance, the notice pay and recovers the whole outstanding loans.")

    def _uae_leave_days(self, pay_rate):
        """Days of approved time off at `pay_rate` ('0' unpaid, '50' half pay)
        inside the payslip period."""
        self.ensure_one()
        return self.employee_id._uae_leave_days_between(
            pay_rate, self.date_from, self.date_to, calendar=self.version_id.resource_calendar_id)

    def _uae_leave_deduction(self, pay_rate):
        """Negative amount for the time off at `pay_rate`: gross salary / divisor
        per day (rule parameter, 30 by default). A whole period of unpaid leave
        deducts the full gross salary, whatever the number of days in the month."""
        self.ensure_one()
        days = self._uae_leave_days(pay_rate)
        if not days:
            return 0.0
        gross = self.version_id.l10n_ae_total_salary
        period_days = (self.date_to - self.date_from).days + 1
        if pay_rate == '0' and days >= period_days:
            return -gross
        divisor = self._rule_parameter('l10n_ae_ext_leave_day_divisor')
        return -min(days, divisor) * gross / divisor * DEDUCTION_SHARE[pay_rate]

    # ------------------------------------------------------------------
    # Additions, deductions and loans
    # ------------------------------------------------------------------

    def _uae_sync_inputs(self):
        """Replace the input lines of approved additions/deductions and loan
        instalments on draft UAE monthly payslips:
        - additions/deductions approved and not paid yet, dated up to the end
          of the period (a late one goes to the next payslip);
        - loan instalments due, at most the company's cap (% of gross) in total;
          loans and salary advances are separate payslip lines.
        """
        monthly = self.env.ref('hr_uae_payroll_ext.structure_uae_monthly')
        loan_inputs = {
            'loan': self.env.ref('hr_uae_payroll_ext.input_loan_recovery'),
            'advance': self.env.ref('hr_uae_payroll_ext.input_advance_recovery'),
        }
        for slip in self.filtered(lambda s: s.state == 'draft' and s.employee_id):
            commands = [Command.unlink(line.id) for line in slip.input_line_ids
                        if line.uae_adjustment_id or line.uae_loan_id]
            if slip.struct_id == monthly:
                adjustments = self.env['hr.payroll.adjustment'].search([
                    ('employee_id', '=', slip.employee_id.id),
                    ('state', '=', 'approved'),
                    ('date', '<=', slip.date_to),
                ], order='date, id')
                commands += [Command.create({
                    'name': '%s: %s' % (adjustment.name, adjustment.reason),
                    'input_type_id': adjustment._uae_input_type().id,
                    'amount': adjustment.amount,
                    'uae_adjustment_id': adjustment.id,
                }) for adjustment in adjustments]

                loans = self.env['hr.employee.loan'].search([
                    ('employee_id', '=', slip.employee_id.id),
                    ('state', '=', 'running'),
                ], order='first_deduction_date, id')
                cap_rate = slip.company_id.uae_loan_deduction_cap
                room = slip.version_id.l10n_ae_total_salary * cap_rate / 100 if cap_rate else None
                if slip.uae_end_of_service_id:
                    # Final settlement: everything outstanding, no cap.
                    room = None
                for loan in loans:
                    amount = loan._uae_due_amount(slip, final=bool(slip.uae_end_of_service_id))
                    if room is not None:
                        amount = min(amount, room)
                        room -= amount
                    amount = slip.currency_id.round(amount)
                    if amount > 0:
                        commands.append(Command.create({
                            'name': '%s: %s' % (loan.name, dict(loan._fields['loan_type']._description_selection(self.env))[loan.loan_type]),
                            'input_type_id': loan_inputs[loan.loan_type].id,
                            'amount': amount,
                            'uae_loan_id': loan.id,
                        }))
            if commands:
                slip.write({'input_line_ids': commands})

    def _uae_paid_share(self):
        """Share of the period paid: without unpaid leave and days out of contract."""
        self.ensure_one()
        period_days = (self.date_to - self.date_from).days + 1
        version = self.version_id
        out_days = max(0, (version.date_start - self.date_from).days) \
            + max(0, (self.date_to - (version.date_end or self.date_to)).days)
        unpaid = min(period_days, self._uae_leave_days('0') + out_days)
        return (period_days - unpaid) / period_days

    def _uae_gratuity_provision(self):
        """Monthly provision for the gratuity: a twelfth of a year of gratuity
        (21 days of basic salary, 30 after 5 years), for the days paid."""
        self.ensure_one()
        join = self.employee_id._ep_join_date()
        years = ((self.date_to - join).days + 1) / 365
        rate = 'l10n_ae_ext_gratuity_tier1_days' if years < self._rule_parameter('l10n_ae_ext_gratuity_tier1_years') \
            else 'l10n_ae_ext_gratuity_tier2_days'
        daily = self.version_id.wage / self._rule_parameter('l10n_ae_ext_gratuity_day_divisor')
        return daily * self._rule_parameter(rate) / 12 * self._uae_paid_share()

    def _uae_leave_provision(self):
        """Monthly provision for the annual leave: a twelfth of a year of leave
        on the basic salary (as paid when leaving), for the days paid."""
        self.ensure_one()
        daily = self.version_id.wage / self._rule_parameter('l10n_ae_ext_leave_encash_divisor')
        return daily * self._rule_parameter('l10n_ae_ext_annual_leave_days_per_year') / 12 * self._uae_paid_share()

    def _uae_settlement_amount(self, kind):
        """Final settlement amounts, for the salary rules: 'gratuity', 'leave'
        (annual leave balance, negative when more was taken than earned) and
        'notice' (pay in lieu of notice, negative when the employee owes it)."""
        self.ensure_one()
        eos = self.uae_end_of_service_id
        if not eos:
            return 0.0
        if kind == 'gratuity':
            return self.employee_id._uae_gratuity(eos.last_working_day)['amount']
        if kind == 'leave':
            return self.employee_id._uae_annual_leave_settlement(eos.last_working_day)['amount']
        if kind == 'notice':
            return eos._uae_notice_amount()
        raise ValueError(kind)

    # ------------------------------------------------------------------
    # Printed payslip
    # ------------------------------------------------------------------

    def _uae_report_values(self):
        """Earnings and deductions of the printed payslip, each with its detail
        (leave days, reason, loan balance); deductions as positive amounts."""
        self.ensure_one()
        earnings, deductions = [], []
        for line in self.line_ids.filtered(
                lambda l: l.appears_on_payslip and not self.currency_id.is_zero(l.total)
                and l.code not in REPORT_TOTAL_CODES and l.category_id.code not in REPORT_TOTAL_CODES):
            row = {'name': line.name, 'amount': abs(line.total), 'detail': self._uae_report_detail(line)}
            (earnings if line.total > 0 else deductions).append(row)
        return {
            'earnings': earnings,
            'deductions': deductions,
            'total_earnings': sum(row['amount'] for row in earnings),
            'total_deductions': sum(row['amount'] for row in deductions),
        }

    def _uae_report_detail(self, line):
        """Short explanation under a payslip line on the printed payslip."""
        if line.code in LEAVE_RULE_RATES:
            days = self._uae_leave_days(LEAVE_RULE_RATES[line.code])
            if LEAVE_RULE_RATES[line.code] == '50':
                return self.env._("%s days at half pay", '%g' % days)
            return self.env._("%s days", '%g' % days)
        details = []
        for slip_input in self.input_line_ids.filtered(lambda i: i.code == line.code):
            adjustment, loan = slip_input.uae_adjustment_id, slip_input.uae_loan_id
            if adjustment:
                details.append(adjustment.reason or adjustment.name)
            elif loan:
                recovered = sum(loan.input_line_ids.filtered(
                    lambda i: i == slip_input or (i.payslip_id.state in ('validated', 'paid')
                                                  and i.payslip_id.date_to <= self.date_to)).mapped('amount'))
                details.append(self.env._("%(loan)s: balance after this payslip %(balance)s",
                                          loan=loan.name, balance=loan.currency_id.format(loan.amount - recovered)))
        return '; '.join(details)

    def compute_sheet(self):
        self._uae_sync_inputs()
        return super().compute_sheet()

    def _uae_update_linked_records(self):
        """Additions/deductions are paid when their payslip is validated, and
        approved again when it is cancelled or reset; loans follow their
        outstanding amount."""
        for slip in self:
            adjustments = slip.input_line_ids.uae_adjustment_id
            if slip.state in ('validated', 'paid'):
                adjustments.write({'state': 'paid', 'payslip_id': slip.id})
            else:
                adjustments.filtered(lambda a: a.payslip_id == slip).write({'state': 'approved', 'payslip_id': False})
        self.input_line_ids.uae_loan_id._uae_update_state()

    def action_payslip_done(self):
        result = super().action_payslip_done()
        self._uae_update_linked_records()
        return result

    def action_payslip_cancel(self):
        result = super().action_payslip_cancel()
        self._uae_update_linked_records()
        return result

    def action_payslip_draft(self):
        result = super().action_payslip_draft()
        self._uae_update_linked_records()
        return result
