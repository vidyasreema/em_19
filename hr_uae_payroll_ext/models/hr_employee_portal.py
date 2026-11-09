from datetime import datetime, time

import pytz
from dateutil.relativedelta import relativedelta

from odoo import fields, models
from odoo.exceptions import UserError

# Records shown to the employee: not drafts nor refused ones.
PORTAL_ADJUSTMENT_STATES = ('to_approve', 'approved', 'paid')
PORTAL_LOAN_STATES = ('to_approve', 'running', 'closed', 'refused')
SETTLEMENT_REPORT_STATES = ('settlement', 'done')
# Days of the attendance calendar: worked, on leave (paid, half a day, unpaid),
# public holiday, not a working day, still to come, not under contract.
DAY_KINDS = ('present', 'leave', 'half', 'unpaid', 'holiday', 'off', 'future', 'out')


class HrEmployee(models.Model):
    """Employee portal helpers for this module's records.

    Like hr_employee_portal, the portal controller calls these on its sudo()-ed
    employee: every method only reads or creates records of that employee.
    """
    _inherit = 'hr.employee'

    def _ep_loans(self):
        self.ensure_one()
        return self.env['hr.employee.loan'].search([
            ('employee_id', '=', self.id), ('state', 'in', PORTAL_LOAN_STATES),
        ], order='date desc, id desc')

    def _ep_adjustments(self, limit=None):
        self.ensure_one()
        return self.env['hr.payroll.adjustment'].search([
            ('employee_id', '=', self.id), ('state', 'in', PORTAL_ADJUSTMENT_STATES),
        ], order='date desc, id desc', limit=limit)

    def _ep_end_of_service(self):
        """The current end of service, if any (not cancelled)."""
        self.ensure_one()
        return self.env['hr.end.of.service'].search([
            ('employee_id', '=', self.id), ('state', '!=', 'cancel'),
        ], order='id desc', limit=1)

    def _ep_create_loan_request(self, loan_type, amount, installment_count, reason):
        """Loan or salary advance requested by the employee: sent for approval.
        Raises UserError with a message for the employee."""
        self.ensure_one()
        if loan_type not in ('loan', 'advance'):
            raise UserError(self.env._("Choose a loan or a salary advance."))
        if amount <= 0:
            raise UserError(self.env._("Enter the amount you need."))
        if loan_type == 'advance':
            installment_count = 1
        if installment_count < 1:
            raise UserError(self.env._("Enter the number of months to repay."))
        if not (reason or '').strip():
            raise UserError(self.env._("Tell HR why you need it."))
        loan = self.env['hr.employee.loan'].create({
            'employee_id': self.id,
            'loan_type': loan_type,
            'amount': amount,
            'installment_count': installment_count,
            'reason': reason.strip(),
        })
        if errors := loan._uae_limit_errors():
            raise UserError(self.env._("This is above what the company allows: %s.", '; '.join(errors)))
        loan.action_submit()
        return loan

    def _ep_attendance(self, month_start):
        """Attendance of a month worked out from the work schedule and approved
        leave, as payroll counts it: nothing is clocked in. Each day is one of
        DAY_KINDS. Returns the days, their totals and the month's leave."""
        self.ensure_one()
        employee = self.sudo()
        month_end = month_start + relativedelta(months=1, days=-1)
        today = fields.Date.context_today(self)
        tz = pytz.timezone(employee.tz or 'UTC')

        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id), ('state', '=', 'validate'),
            ('request_date_from', '<=', month_end), ('request_date_to', '>=', month_start),
        ], order='request_date_from')
        holidays = self.env['resource.calendar.leaves'].sudo().search([
            ('resource_id', '=', False),
            ('company_id', 'in', [False, employee.company_id.id]),
            ('date_from', '<=', datetime.combine(month_end, time.max)),
            ('date_to', '>=', datetime.combine(month_start - relativedelta(days=1), time.min)),
        ])

        def local_date(value):
            return pytz.utc.localize(value).astimezone(tz).date()

        days, totals, leave_days = [], dict.fromkeys(('working', 'present', 'leave', 'unpaid', 'holiday'), 0.0), {}
        day = month_start
        while day <= month_end:
            version = employee._get_version(day)
            calendar = version.resource_calendar_id or employee.resource_calendar_id
            entry = {'date': day, 'kind': 'off', 'label': '', 'share': 1.0}
            if not version.contract_date_start or day < version.contract_date_start or (
                    version.contract_date_end and day > version.contract_date_end):
                entry['kind'] = 'out'
                days.append(entry)
                day += relativedelta(days=1)
                continue
            working = self._ep_is_working_day(calendar, day)
            holiday = holidays.filtered(lambda h: (not h.calendar_id or h.calendar_id == calendar)
                                        and local_date(h.date_from) <= day <= local_date(h.date_to))[:1]
            leave = leaves.filtered(lambda l: l.request_date_from <= day <= l.request_date_to)[:1]
            counts = leave and (working or leave.holiday_status_id.uae_count_calendar_days)
            if counts:
                share = leave._uae_calendar_days(day, day) if leave.holiday_status_id.uae_count_calendar_days else (
                    0.5 if leave.request_unit_half and leave.request_date_from_period == leave.request_date_to_period else 1.0)
                unpaid = leave.holiday_status_id.uae_pay_rate == '0'
                entry.update(kind='unpaid' if unpaid else ('half' if share < 1 else 'leave'),
                             label=leave.holiday_status_id.name, share=share)
                totals['unpaid' if unpaid else 'leave'] += share
                leave_days[leave] = leave_days.get(leave, 0.0) + share
                if working:
                    totals['working'] += 1
                    if share < 1 and day <= today:
                        totals['present'] += 1 - share
            elif working and holiday:
                entry.update(kind='holiday', label=holiday.name)
                totals['holiday'] += 1
            elif working:
                totals['working'] += 1
                if day > today:
                    entry['kind'] = 'future'
                else:
                    entry['kind'] = 'present'
                    totals['present'] += 1
            days.append(entry)
            day += relativedelta(days=1)
        return {
            'days': days,
            'totals': totals,
            'leaves': [(leave, total) for leave, total in leave_days.items()],
        }

    @staticmethod
    def _ep_is_working_day(calendar, day):
        """Whether the work schedule has hours on this day."""
        if not calendar:
            return day.weekday() < 5
        if calendar.flexible_hours:
            return day.weekday() < 5
        attendances = calendar.attendance_ids.filtered(lambda a: not a.display_type and a.day_period != 'lunch')
        if calendar.two_weeks_calendar:
            week_type = str(calendar.env['resource.calendar.attendance'].get_week_type(day))
            attendances = attendances.filtered(lambda a: a.week_type == week_type)
        return str(day.weekday()) in attendances.mapped('dayofweek')
