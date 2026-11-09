from datetime import datetime, time

from odoo import api, fields, models


def _param(env, code, date):
    return env['hr.rule.parameter']._get_parameter_from_code(code, date)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    uae_unpaid_days_before_odoo = fields.Float(
        string="Unpaid Days Before Odoo", groups="hr.group_hr_user", tracking=True,
        help="Days of unpaid leave taken before the company used Odoo. They are left out of "
             "the service period for the gratuity, like the unpaid leave recorded in Odoo.")

    # ------------------------------------------------------------------
    # Unpaid days, gratuity, annual leave settlement
    # ------------------------------------------------------------------

    def _uae_leave_days_between(self, pay_rate, date_from, date_to, calendar=None):
        """Days of approved time off at `pay_rate` ('0' unpaid, '50' half pay)
        between two dates. Types counted in calendar days give calendar days,
        other types the working days of `calendar`."""
        self.ensure_one()
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.id),
            ('state', '=', 'validate'),
            ('holiday_status_id.uae_pay_rate', '=', pay_rate),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
        ])
        days = 0.0
        for leave in leaves:
            if leave.holiday_status_id.uae_count_calendar_days and leave.leave_type_request_unit != 'hour':
                days += leave._uae_calendar_days(date_from, date_to)
                continue
            if leave.leave_type_request_unit == 'hour' or (
                    leave.request_unit_half and leave.request_date_from == leave.request_date_to):
                # Within one day, so inside the period.
                days += leave.number_of_days
                continue
            start = max(leave.request_date_from, date_from)
            end = min(leave.request_date_to, date_to)
            days += self._get_work_days_data_batch(
                datetime.combine(start, time.min), datetime.combine(end, time.max),
                # compute_leaves would remove the days of this very leave.
                compute_leaves=False, calendar=calendar,
            )[self.id]['days']
        return days

    def _uae_gratuity(self, end_date=None):
        """End of service gratuity (UAE Federal Decree-Law 33/2021, art. 51) on
        `end_date` (today by default), from the rule parameters valid then:
        - nothing below the minimum service (1 year);
        - 21 days of basic salary per year for the first 5 years, 30 days after;
        - at most 2 years of basic salary;
        - unpaid leave is left out of the service period.
        The basic salary is the one of the contract on `end_date`."""
        self.ensure_one()
        employee = self.sudo()
        end_date = end_date or fields.Date.today()
        start = employee._ep_join_date()
        unpaid_days = employee._uae_leave_days_between('0', start, end_date) + employee.uae_unpaid_days_before_odoo
        service_days = max(0.0, (end_date - start).days + 1 - unpaid_days)
        years = service_days / 365
        basic = (employee._get_version(end_date) or employee.version_id).wage

        min_years = _param(self.env, 'l10n_ae_ext_gratuity_min_years', end_date)
        tier1_years = _param(self.env, 'l10n_ae_ext_gratuity_tier1_years', end_date)
        tier1_days = _param(self.env, 'l10n_ae_ext_gratuity_tier1_days', end_date)
        tier2_days = _param(self.env, 'l10n_ae_ext_gratuity_tier2_days', end_date)
        cap_months = _param(self.env, 'l10n_ae_ext_gratuity_cap_months', end_date)
        daily = basic / _param(self.env, 'l10n_ae_ext_gratuity_day_divisor', end_date)

        tier1 = min(years, tier1_years) * tier1_days * daily
        tier2 = max(0.0, years - tier1_years) * tier2_days * daily
        cap = basic * cap_months
        eligible = years >= min_years
        amount = min(tier1 + tier2, cap) if eligible else 0.0
        return {
            'start_date': start,
            'end_date': end_date,
            'unpaid_days': unpaid_days,
            'service_days': service_days,
            'years': years,
            'basic': basic,
            'daily_salary': daily,
            'tier1_years': min(years, tier1_years),
            'tier1_days': tier1_days,
            'tier1_amount': tier1 if eligible else 0.0,
            'tier2_years': max(0.0, years - tier1_years),
            'tier2_days': tier2_days,
            'tier2_amount': tier2 if eligible else 0.0,
            'eligible': eligible,
            'capped': eligible and tier1 + tier2 > cap,
            'amount': employee.company_id.currency_id.round(amount),
        }

    def _uae_annual_leave_settlement(self, end_date):
        """Annual leave balance to pay (positive) or deduct (negative) when the
        employee leaves on `end_date`. The days of the current contract are given
        upfront, so the part not earned yet (days per year x time left) is taken
        out: e.g. 60 days for 2 years, leaving after 1 year with 40 days taken
        gives 20 left - 30 not earned = -10 days to deduct."""
        self.ensure_one()
        employee = self.sudo()
        leave_types = self.env['hr.leave.type'].sudo().search([('uae_days_per_contract', '>', 0)])
        allocations = self.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee.id),
            ('holiday_status_id', 'in', leave_types.ids),
            ('state', '=', 'validate'),
            ('date_from', '<=', end_date),
        ])
        taken = sum(self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('holiday_status_id', 'in', leave_types.ids),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', end_date),
        ]).mapped('number_of_days'))
        remaining = sum(allocations.mapped('number_of_days')) - taken

        not_earned = 0.0
        contract_start = (employee._get_version(end_date) or employee.version_id).contract_date_start
        current = allocations.filtered(lambda a: a.uae_contract_start == contract_start)
        if current:
            days_per_year = _param(self.env, 'l10n_ae_ext_annual_leave_days_per_year', end_date)
            earned = ((end_date - contract_start).days + 1) / 365 * days_per_year
            not_earned = max(0.0, sum(current.holiday_status_id.mapped('uae_days_per_contract')) - earned)
        days = remaining - not_earned

        basic = (employee._get_version(end_date) or employee.version_id).wage
        daily = basic / _param(self.env, 'l10n_ae_ext_leave_encash_divisor', end_date)
        return {
            'remaining_days': remaining,
            'not_earned_days': not_earned,
            'days': days,
            'daily_salary': daily,
            'amount': employee.company_id.currency_id.round(days * daily),
        }

    def _uae_create_leave_allocations(self):
        """Create the leave balances employees are missing. Returns the new allocations.

        - Types with "Days per Contract" (annual leave): that many days for each
          contract, from the contract start. A renewal gets a new allocation and,
          as allocations have no end date, unused days carry over to it.
        - Types with an accrual plan (sick leave): one accrual allocation, giving
          the full yearly days every 1 January.
        """
        employees = self.filtered('active')
        allocations = employees._uae_create_contract_allocations()
        allocations |= employees._uae_create_accrual_allocations()
        return allocations

    def _uae_create_contract_allocations(self):
        leave_types = self.env['hr.leave.type'].search([('uae_days_per_contract', '>', 0)])
        Allocation = self.env['hr.leave.allocation']
        existing = {
            (allocation.employee_id.id, allocation.holiday_status_id.id, allocation.uae_contract_start)
            for allocation in Allocation.search([
                ('employee_id', 'in', self.ids),
                ('holiday_status_id', 'in', leave_types.ids),
                ('uae_contract_start', '!=', False),
                ('state', '!=', 'refuse'),
            ])
        }
        values = []
        for employee in self:
            contract_start = employee.sudo().current_version_id.contract_date_start
            if not contract_start:
                continue
            for leave_type in leave_types:
                if leave_type.company_id and leave_type.company_id != employee.company_id:
                    continue
                if (employee.id, leave_type.id, contract_start) in existing:
                    continue
                values.append({
                    'name': self.env._("%(type)s, contract from %(date)s", type=leave_type.name, date=contract_start),
                    'employee_id': employee.id,
                    'holiday_status_id': leave_type.id,
                    'allocation_type': 'regular',
                    'number_of_days': leave_type.uae_days_per_contract,
                    'date_from': contract_start,
                    'uae_contract_start': contract_start,
                })
        allocations = Allocation.create(values)
        allocations.action_approve()
        return allocations

    def _uae_create_accrual_allocations(self):
        leave_types = self.env['hr.leave.type'].search([
            ('requires_allocation', '=', True),
            ('accruals_ids', '!=', False),
        ])
        Allocation = self.env['hr.leave.allocation']
        existing = {
            (allocation.employee_id.id, allocation.holiday_status_id.id)
            for allocation in Allocation.search([
                ('employee_id', 'in', self.ids),
                ('holiday_status_id', 'in', leave_types.ids),
                ('state', '!=', 'refuse'),
            ])
        }
        values = []
        for employee in self:
            for leave_type in leave_types:
                if leave_type.company_id and leave_type.company_id != employee.company_id:
                    continue
                if (employee.id, leave_type.id) in existing:
                    continue
                plan = leave_type.accruals_ids[:1]
                values.append({
                    'name': plan.name,
                    'employee_id': employee.id,
                    'holiday_status_id': leave_type.id,
                    'allocation_type': 'accrual',
                    'accrual_plan_id': plan.id,
                    # From 1 January of the join year: the full yearly days, even
                    # for employees joining during the year (no prorata).
                    'date_from': employee._ep_join_date().replace(month=1, day=1),
                    'number_of_days': 0,
                })
        allocations = Allocation.create(values)
        # Created in code, an accrual starts today. Replay it from its start date,
        # as the allocation form does when the start date is entered.
        for allocation in allocations:
            allocation.write({'lastcall': allocation.date_from, 'nextcall': False, 'number_of_days': 0})
        allocations._process_accrual_plans(fields.Date.today())
        allocations.action_approve()
        return allocations

    @api.model
    def _cron_uae_create_leave_allocations(self):
        """Daily: balances for new employees and for contracts renewed today."""
        self.search([])._uae_create_leave_allocations()

    def action_uae_create_leave_allocations(self):
        allocations = self._uae_create_leave_allocations()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if allocations else 'info',
                'message': self.env._("%s allocations created.", len(allocations)) if allocations
                           else self.env._("Every employee already has these allocations."),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
