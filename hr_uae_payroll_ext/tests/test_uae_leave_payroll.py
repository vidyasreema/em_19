from datetime import date, datetime, time

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class UaePayrollCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'UAE Test Company',
            'country_id': cls.env.ref('base.ae').id,
            'currency_id': cls.env.ref('base.AED').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=cls.company.ids))
        # Mon-Fri, 8 hours a day.
        cls.calendar = cls.env['resource.calendar'].create({'name': 'UAE 40h', 'company_id': cls.company.id})
        cls.structure = cls.env.ref('hr_uae_payroll_ext.structure_uae_monthly')
        cls.annual = cls.env.ref('hr_uae_payroll_ext.leave_type_annual')
        cls.unpaid = cls.env.ref('hr_uae_payroll_ext.leave_type_unpaid')
        cls.sick_full = cls.env.ref('hr_uae_payroll_ext.leave_type_sick_full')
        cls.sick_half = cls.env.ref('hr_uae_payroll_ext.leave_type_sick_half')
        cls.parental = cls.env.ref('hr_uae_payroll_ext.leave_type_parental')
        cls.join_date = fields.Date.today() - relativedelta(months=18, day=1)
        # Gross 6,000: basic 4,000 + housing 1,500 + transport 500.
        cls.employee = cls._create_employee('UAE Employee', cls.join_date)

    @classmethod
    def _create_employee(cls, name, join_date, contract_end=False):
        return cls.env['hr.employee'].create({
            'name': name,
            'company_id': cls.company.id,
            'resource_calendar_id': cls.calendar.id,
            'contract_date_start': join_date,
            'contract_date_end': contract_end,
            'date_version': join_date,
            'structure_type_id': cls.structure.type_id.id,
            'wage': 4000.0,
            'l10n_ae_housing_allowance': 1500.0,
            'l10n_ae_transportation_allowance': 500.0,
        })

    def _leave(self, leave_type, start, end, employee=None, periods=None):
        values = {
            'employee_id': (employee or self.employee).id,
            'holiday_status_id': leave_type.id,
            'request_date_from': start,
            'request_date_to': end,
        }
        if periods:
            values.update(request_date_from_period=periods[0], request_date_to_period=periods[1])
        leave = self.env['hr.leave'].create(values)
        leave.action_approve()
        return leave

    def _payslip(self, month_start):
        payslip = self.env['hr.payslip'].create({
            'name': 'Test payslip',
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'struct_id': self.structure.id,
            'date_from': month_start,
            'date_to': month_start + relativedelta(day=31),
        })
        payslip.compute_sheet()
        return payslip

    def _line_total(self, payslip, code):
        return sum(payslip.line_ids.filtered(lambda line: line.code == code).mapped('total'))


class TestUaeLeave(UaePayrollCommon):

    def test_pay_rate_follows_work_entry_type(self):
        self.assertEqual(self.unpaid.uae_pay_rate, '0')
        self.assertEqual(self.sick_half.uae_pay_rate, '50')
        self.assertEqual(self.sick_full.uae_pay_rate, '100')
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Other unpaid', 'requires_allocation': False,
            'work_entry_type_id': self.env.ref('hr_work_entry.work_entry_type_unpaid_leave').id,
        })
        self.assertEqual(leave_type.uae_pay_rate, '0')

    def test_calendar_days_include_weekend(self):
        # Friday to the next Monday: 4 calendar days, 2 working days.
        friday = fields.Date.today() + relativedelta(weeks=2, weekday=4)
        unpaid = self._leave(self.unpaid, friday, friday + relativedelta(days=3))
        self.assertEqual(unpaid.number_of_days, 4)
        parental = self._leave(self.parental, friday + relativedelta(weeks=1), friday + relativedelta(weeks=1, days=3))
        self.assertEqual(parental.number_of_days, 2)

    def test_half_days(self):
        self.employee._uae_create_leave_allocations()
        friday = fields.Date.today() + relativedelta(weeks=2, weekday=4)
        morning = self._leave(self.annual, friday, friday, periods=('am', 'am'))
        self.assertEqual(morning.number_of_days, 0.5)
        # Friday afternoon to Monday evening: 3.5 calendar days.
        week_after = friday + relativedelta(weeks=1)
        leave = self._leave(self.annual, week_after, week_after + relativedelta(days=3), periods=('pm', 'pm'))
        self.assertEqual(leave.number_of_days, 3.5)
        # Full days on a half-day type are unchanged.
        self.assertEqual(self._leave(self.unpaid, friday + relativedelta(weeks=2), friday + relativedelta(weeks=2, days=3)).number_of_days, 4)
        self.assertEqual(self.parental.request_unit, 'day', "Not offered in half days")

    def test_one_line_working_day_split_for_half_days(self):
        """A day entered as one 9:00-18:00 "Morning" line becomes "Full Day", so
        an afternoon is 13:30-18:00. A short morning-only day stays a morning."""
        calendar = self.env['resource.calendar'].create({
            'name': 'One line a day', 'company_id': self.company.id, 'hours_per_day': 9,
            'attendance_ids': [(0, 0, {'name': str(day), 'dayofweek': str(day), 'hour_from': 9, 'hour_to': 18,
                                       'day_period': 'morning'}) for day in range(5)]
                              + [(0, 0, {'name': 'Sat', 'dayofweek': '5', 'hour_from': 9, 'hour_to': 13,
                                         'day_period': 'morning'})],
        })
        fixed = self.env['resource.calendar']._uae_mark_full_days()
        self.assertEqual(fixed.filtered(lambda a: a.calendar_id == calendar).mapped('dayofweek'), ['0', '1', '2', '3', '4'])
        self.assertEqual(calendar.attendance_ids.filtered(lambda a: a.dayofweek == '5').day_period, 'morning')
        self.assertEqual(calendar._get_hours_for_date(fields.Date.today() + relativedelta(weekday=0), 'afternoon'), (13.5, 18))

    def test_min_service_months(self):
        newcomer = self._create_employee('Newcomer', fields.Date.today() - relativedelta(months=2))
        newcomer._uae_create_leave_allocations()
        start = fields.Date.today() + relativedelta(days=7)
        self.parental.uae_min_service_months = 6
        with self.assertRaises(ValidationError):
            self._leave(self.parental, start, start, employee=newcomer)
        # Annual leave can be taken from the first month of the contract.
        self.assertEqual(self._leave(self.annual, start, start, employee=newcomer).state, 'validate')

    def test_full_sick_leave_for_new_joiner(self):
        newcomer = self._create_employee('Newcomer', fields.Date.today() - relativedelta(months=2))
        allocations = newcomer._uae_create_leave_allocations()
        days = {a.holiday_status_id: a.number_of_days for a in allocations}
        self.assertEqual(days[self.sick_full], 15)
        self.assertEqual(days[self.sick_half], 30)
        self.assertEqual(days[self.env.ref('hr_uae_payroll_ext.leave_type_sick_unpaid')], 45)

    def test_upcoming_sick_leave_deducted(self):
        today = fields.Date.today()
        if today.month == 12 and today.day > 25:
            self.skipTest("Needs a few days left in the year")
        newcomer = self._create_employee('Upcoming', today - relativedelta(months=2))
        newcomer._uae_create_leave_allocations()
        self._leave(self.sick_full, today + relativedelta(days=1), today + relativedelta(days=2), employee=newcomer)
        balance = next(b for b in newcomer._ep_leave_balances() if b['type'] == self.sick_full)
        self.assertEqual(balance['allocated'], 15)
        self.assertEqual(balance['taken'], 2)
        self.assertEqual(balance['remaining'], 13, "Approved sick leave counts before its date")

    def test_annual_leave_per_contract(self):
        today = fields.Date.today()
        employee = self._create_employee('Renewed', today - relativedelta(years=2), contract_end=today - relativedelta(days=1))
        allocations = employee._uae_create_leave_allocations()
        annual = allocations.filtered(lambda a: a.holiday_status_id == self.annual)
        self.assertEqual(annual.number_of_days, 60)
        self.assertEqual(annual.date_from, today - relativedelta(years=2))
        self.assertEqual(allocations.filtered(lambda a: a.holiday_status_id == self.sick_full).number_of_days, 15)
        self.assertFalse(employee._uae_create_leave_allocations(), "Allocations are created once")

        # 40 days taken in the first year of the contract.
        first_day = today - relativedelta(years=2) + relativedelta(months=2)
        self._leave(self.annual, first_day, first_day + relativedelta(days=39), employee=employee)

        # Renewal: 60 new days, the 20 left carry over.
        employee.create_version({
            'date_version': today,
            'contract_date_start': today,
            'contract_date_end': today + relativedelta(years=2, days=-1),
        })
        renewal = employee._uae_create_leave_allocations()
        self.assertEqual(renewal.holiday_status_id, self.annual)
        self.assertEqual(renewal.uae_contract_start, today)
        balance = next(b for b in employee._ep_leave_balances() if b['type'] == self.annual)
        self.assertEqual(balance['remaining'], 80)

    def test_archive_unused_types(self):
        LeaveType = self.env['hr.leave.type']
        belgium = self.env.ref('base.be')
        unused = LeaveType.create({'name': 'BE unused', 'country_id': belgium.id, 'requires_allocation': False})
        used = LeaveType.create({'name': 'BE used', 'country_id': belgium.id, 'requires_allocation': False})
        self.env['hr.leave'].create({
            'employee_id': self.employee.id, 'holiday_status_id': used.id,
            'request_date_from': fields.Date.today() + relativedelta(days=10),
            'request_date_to': fields.Date.today() + relativedelta(days=10),
        })
        LeaveType._uae_archive_unused_types()
        self.assertFalse(unused.active)
        self.assertTrue(used.active)
        self.assertTrue(self.annual.active)


class TestUaeLeavePayroll(UaePayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee._uae_create_leave_allocations()
        cls.month = fields.Date.today() + relativedelta(months=1, day=1)
        # First Monday of the month: leaves on working days.
        cls.monday = cls.month + relativedelta(weekday=0)

    def test_unpaid_leave_calendar_days(self):
        # 3 calendar days: 6,000 / 30 * 3.
        self._leave(self.unpaid, self.monday, self.monday + relativedelta(days=2))
        payslip = self._payslip(self.month)
        self.assertAlmostEqual(self._line_total(payslip, 'UAEUNPAID'), -600)
        self.assertFalse(self._line_total(payslip, 'AEUNPAID'), "The standard rule is archived")

    def test_half_pay_leave(self):
        # 2 days at half pay: 6,000 / 30 * 2 * 0.5.
        self._leave(self.sick_half, self.monday + relativedelta(days=7), self.monday + relativedelta(days=8))
        payslip = self._payslip(self.month)
        self.assertAlmostEqual(self._line_total(payslip, 'UAEHALFPAY'), -200)

    def test_half_day_unpaid(self):
        # Half a day: 6,000 / 30 * 0.5.
        self._leave(self.unpaid, self.monday, self.monday, periods=('pm', 'pm'))
        self.assertAlmostEqual(self._line_total(self._payslip(self.month), 'UAEUNPAID'), -100)

    def test_leave_across_two_months(self):
        # Last 2 days of this month, first 3 days of the next.
        month_end = self.month + relativedelta(day=31)
        self._leave(self.unpaid, month_end - relativedelta(days=1), month_end + relativedelta(days=3))
        self.assertAlmostEqual(self._line_total(self._payslip(self.month), 'UAEUNPAID'), -400)
        next_month = self.month + relativedelta(months=1)
        self.assertAlmostEqual(self._line_total(self._payslip(next_month), 'UAEUNPAID'), -600)

    def test_whole_month_unpaid(self):
        self._leave(self.unpaid, self.month, self.month + relativedelta(day=31))
        self.assertAlmostEqual(self._line_total(self._payslip(self.month), 'UAEUNPAID'), -6000)

    def test_no_leave_no_line(self):
        payslip = self._payslip(self.month)
        self.assertFalse(payslip.line_ids.filtered(lambda line: line.code in ('UAEUNPAID', 'UAEHALFPAY')))

    def test_divisor_is_a_parameter(self):
        self.env.ref('hr_uae_payroll_ext.rule_parameter_leave_day_divisor_2020').parameter_value = '26'
        self._leave(self.unpaid, self.monday, self.monday)
        self.assertAlmostEqual(self._line_total(self._payslip(self.month), 'UAEUNPAID'), -6000 / 26, places=2)


class TestUaeAttendance(UaePayrollCommon):
    """Attendance worked out from the Mon-Fri schedule and approved leave."""

    def test_month(self):
        self.employee._uae_create_leave_allocations()
        month = fields.Date.today() + relativedelta(months=-1, day=1)
        monday = month + relativedelta(weekday=0)
        if monday.day == 1:
            monday += relativedelta(weeks=1)
        # Annual leave Monday to Tuesday, a public holiday on Thursday
        self._leave(self.annual, monday, monday + relativedelta(days=1))
        thursday = monday + relativedelta(days=3)
        self.env['resource.calendar.leaves'].create({
            'name': 'National Day', 'company_id': self.company.id,
            'date_from': datetime.combine(thursday, time(6)), 'date_to': datetime.combine(thursday, time(18)),
        })
        data = self.employee._ep_attendance(month)
        kinds = {d['date']: d['kind'] for d in data['days']}
        self.assertEqual(kinds[monday], 'leave')
        self.assertEqual(kinds[monday + relativedelta(days=2)], 'present')
        self.assertEqual(kinds[thursday], 'holiday')
        self.assertEqual(kinds[monday + relativedelta(days=5)], 'off', "Saturday")
        weekdays = sum(1 for d in data['days'] if d['date'].weekday() < 5)
        totals = data['totals']
        self.assertEqual(totals['holiday'], 1)
        self.assertEqual(totals['leave'], 2)
        self.assertEqual(totals['working'], weekdays - 1)
        self.assertEqual(totals['present'], weekdays - 3)
        self.assertEqual(data['leaves'][0][1], 2)

    def test_half_day_unpaid_and_before_contract(self):
        newcomer = self._create_employee('Newcomer', fields.Date.today() - relativedelta(days=20))
        start = newcomer.version_id.contract_date_start
        day = start + relativedelta(weekday=0) if start.weekday() > 4 else start
        month = day.replace(day=1)
        self._leave(self.unpaid, day, day, employee=newcomer, periods=('pm', 'pm'))
        data = newcomer._ep_attendance(month)
        kinds = {d['date']: d for d in data['days']}
        if start > month:
            self.assertEqual(kinds[month]['kind'], 'out')
        self.assertEqual(kinds[day]['kind'], 'unpaid')
        self.assertEqual(kinds[day]['share'], 0.5)
        self.assertEqual(data['totals']['unpaid'], 0.5)


class TestUaeStructure(UaePayrollCommon):

    def test_company_structure_is_default(self):
        self.assertEqual(self.employee.version_id.structure_type_id.default_struct_id, self.structure)
        payslip = self.env['hr.payslip'].create({
            'name': 'Default structure', 'employee_id': self.employee.id, 'version_id': self.employee.version_id.id,
            'date_from': fields.Date.today().replace(day=1),
            'date_to': fields.Date.today() + relativedelta(day=31),
        })
        self.assertEqual(payslip.struct_id, self.structure)

    def test_monthly_payslip(self):
        # Basic 4,000 + housing 1,500 + transport 500; provisions are not on the payslip.
        payslip = self._payslip(fields.Date.today() + relativedelta(months=1, day=1))
        shown = payslip.line_ids.filtered('appears_on_payslip')
        self.assertEqual(set(shown.mapped('code')), {'BASIC', 'HOUALLOW', 'TRAALLOW', 'GROSS', 'NET'})
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 6000)
        # Gratuity provision: 21 days of 4,000 / 30 a year, a twelfth a month.
        self.assertAlmostEqual(self._line_total(payslip, 'EOSP'), 4000 / 30 * 21 / 12, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'ALP'), 4000 / 30 * 30 / 12, places=2)

    def test_only_company_rules(self):
        codes = set(self.structure.rule_ids.mapped('code'))
        for unused in ('SICC', 'SIEC', 'DEWS', 'OT', 'EOS', 'ALEA', 'ALED', 'AEUNPAID', 'HOUALLOWINP'):
            self.assertNotIn(unused, codes)
