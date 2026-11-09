from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from .test_uae_leave_payroll import UaePayrollCommon

# Basic salary 4,000 (UaePayrollCommon): 4,000 / 30 a day.
DAILY = 4000 / 30


@tagged('post_install', '-at_install')
class TestGratuity(UaePayrollCommon):

    def _gratuity(self, join, end, **employee_vals):
        employee = self._create_employee('Gratuity', join)
        if employee_vals:
            employee.write(employee_vals)
        return employee._uae_gratuity(end)

    def test_less_than_one_year(self):
        result = self._gratuity(date(2023, 1, 1), date(2023, 12, 30))
        self.assertFalse(result['eligible'])
        self.assertEqual(result['amount'], 0)

    def test_three_years(self):
        # 2021-2023: 1,095 days, exactly 3 years at 21 days.
        result = self._gratuity(date(2021, 1, 1), date(2023, 12, 31))
        self.assertAlmostEqual(result['years'], 3)
        self.assertAlmostEqual(result['amount'], 3 * 21 * DAILY, places=2)

    def test_more_than_five_years(self):
        result = self._gratuity(date(2015, 1, 1), date(2021, 12, 31))
        expected = 5 * 21 * DAILY + (result['years'] - 5) * 30 * DAILY
        self.assertAlmostEqual(result['amount'], expected, places=2)
        self.assertAlmostEqual(result['tier1_amount'], 5 * 21 * DAILY, places=2)

    def test_two_years_cap(self):
        result = self._gratuity(date(1990, 1, 1), date(2021, 12, 31))
        self.assertTrue(result['capped'])
        self.assertEqual(result['amount'], 24 * 4000)

    def test_unpaid_days_left_out(self):
        # 1 year and 10 days of service, minus 20 unpaid days: under 1 year.
        join = date(2022, 1, 1)
        end = join + relativedelta(years=1, days=9)
        self.assertTrue(self._gratuity(join, end)['eligible'])
        result = self._gratuity(join, end, uae_unpaid_days_before_odoo=20)
        self.assertFalse(result['eligible'])
        self.assertEqual(result['unpaid_days'], 20)

    def test_unpaid_leave_in_odoo_left_out(self):
        employee = self._create_employee('Unpaid', date(2021, 1, 1))
        leave = self.env['hr.leave'].create({
            'employee_id': employee.id,
            'holiday_status_id': self.unpaid.id,
            'request_date_from': date(2022, 3, 7),
            'request_date_to': date(2022, 3, 16),
        })
        leave.action_approve()
        result = employee._uae_gratuity(date(2023, 12, 31))
        self.assertEqual(result['unpaid_days'], 10)
        self.assertAlmostEqual(result['service_days'], 1095 - 10)

    def test_rules_are_parameters(self):
        self.env.ref('hr_uae_payroll_ext.rule_parameter_gratuity_tier1_days_2020').parameter_value = '15'
        result = self._gratuity(date(2021, 1, 1), date(2023, 12, 31))
        self.assertAlmostEqual(result['amount'], 3 * 15 * DAILY, places=2)


@tagged('post_install', '-at_install')
class TestLeaveSettlement(UaePayrollCommon):

    def test_more_taken_than_earned(self):
        # 60 days for a 2-year contract, leaving after 1 year with 40 days taken:
        # 20 left - 30 not earned = -10 days.
        today = fields.Date.today()
        start = today - relativedelta(years=1, days=-1)
        employee = self._create_employee('Leaver', start, contract_end=start + relativedelta(years=2, days=-1))
        employee._uae_create_leave_allocations()
        first = start + relativedelta(months=1)
        self._leave(self.annual, first, first + relativedelta(days=39), employee=employee)
        result = employee._uae_annual_leave_settlement(today)
        self.assertAlmostEqual(result['remaining_days'], 20)
        self.assertAlmostEqual(result['days'], -10, delta=0.1)
        self.assertAlmostEqual(result['amount'], result['days'] * DAILY, delta=0.01)

    def test_unused_days_paid(self):
        # Contract renewed with 15 days left from the previous one, leaving at the
        # end of the new contract with nothing taken: 15 + 60 days paid.
        today = fields.Date.today()
        employee = self._create_employee('Long', today - relativedelta(years=4), contract_end=today - relativedelta(years=2, days=1))
        old = employee._uae_create_leave_allocations().filtered(lambda a: a.holiday_status_id == self.annual)
        old.number_of_days = 15  # opening balance
        employee.create_version({
            'date_version': today - relativedelta(years=2),
            'contract_date_start': today - relativedelta(years=2),
            'contract_date_end': today + relativedelta(days=1),
        })
        employee._uae_create_leave_allocations()
        result = employee._uae_annual_leave_settlement(today + relativedelta(days=1))
        self.assertAlmostEqual(result['days'], 75, delta=0.2)


@tagged('post_install', '-at_install')
class TestEndOfService(UaePayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login='uae_eos_manager',
            groups='base.group_user,hr.group_hr_user,hr_payroll.group_hr_payroll_manager',
            company_id=cls.company.id, company_ids=cls.company.ids)

    def _end_of_service(self, **vals):
        eos = self.env['hr.end.of.service'].create(dict({
            'employee_id': self.employee.id,
            'reason': 'resignation',
            'notice_date': fields.Date.today(),
        }, **vals))
        eos.action_submit()
        eos.with_user(self.manager).action_approve()
        return eos

    def test_last_working_day_from_notice(self):
        eos = self.env['hr.end.of.service'].create({
            'employee_id': self.employee.id, 'notice_date': date(2026, 11, 1), 'notice_days': 30,
        })
        self.assertEqual(eos.last_working_day, date(2026, 11, 30))
        self.assertTrue(eos.name.startswith('EOS/'))

    def test_full_flow(self):
        loan = self.env['hr.employee.loan'].create({
            'employee_id': self.employee.id, 'amount': 3000, 'installment_count': 6,
            'first_deduction_date': fields.Date.today() + relativedelta(months=1, day=1), 'reason': 'Test',
        })
        loan.with_user(self.manager).action_approve()

        eos = self._end_of_service()
        self.assertEqual(eos.state, 'approved')
        self.assertEqual(self.employee.version_id.contract_date_end, eos.last_working_day)
        self.assertEqual(eos.loan_amount, 3000)

        eos.action_create_settlement()
        payslip = eos.payslip_id
        self.assertEqual(eos.state, 'settlement')
        self.assertEqual(payslip.uae_end_of_service_id, eos)
        gratuity = self.employee._uae_gratuity(eos.last_working_day)['amount']
        self.assertTrue(gratuity > 0)
        self.assertAlmostEqual(self._line_total(payslip, 'UAEGRAT'), gratuity)
        self.assertAlmostEqual(self._line_total(payslip, 'UAELOAN'), -3000, msg="Whole loan, no cap")
        self.assertAlmostEqual(eos.gratuity_amount, gratuity)

        with self.assertRaises(UserError):
            eos.with_user(self.manager).action_done()
        payslip.action_payslip_done()
        self.assertEqual(loan.state, 'closed')
        eos.with_user(self.manager).action_done()
        self.assertEqual(eos.state, 'done')
        self.assertFalse(self.employee.active)
        self.assertEqual(self.employee.departure_date, eos.last_working_day)
        self.assertEqual(self.employee.departure_reason_id, self.env.ref('hr.departure_resigned'))

    def test_report_renders(self):
        eos = self._end_of_service()
        eos.action_create_settlement()
        html = self.env['ir.actions.report']._render_qweb_html(
            'hr_uae_payroll_ext.action_report_final_settlement', eos.ids)[0]
        self.assertIn(b'Final Settlement', html)

    def test_notice_in_lieu(self):
        # Leaves the day of the notice: 29 of the 30 notice days not worked.
        today = fields.Date.today()
        eos = self._end_of_service(notice_pay='pay', last_working_day=today)
        self.assertEqual(eos.notice_pay_days, 29)
        self.assertAlmostEqual(eos.notice_amount, 29 * 6000 / 30)
        eos.notice_pay = 'deduct'
        self.assertAlmostEqual(eos.notice_amount, -29 * 6000 / 30)
        eos.action_create_settlement()
        self.assertAlmostEqual(self._line_total(eos.payslip_id, 'UAENOTICEDED'), -29 * 6000 / 30)

    def test_existing_draft_payslip_used(self):
        eos = self._end_of_service()
        month = eos.last_working_day.replace(day=1)
        draft = self._payslip(month)
        eos.action_create_settlement()
        self.assertEqual(eos.payslip_id, draft)

    def test_validated_payslip_blocks(self):
        eos = self._end_of_service()
        self._payslip(eos.last_working_day.replace(day=1)).action_payslip_done()
        with self.assertRaises(UserError):
            eos.action_create_settlement()

    def test_cancel_restores_contract_end(self):
        eos = self._end_of_service()
        eos.action_create_settlement()
        payslip = eos.payslip_id
        eos.action_cancel()
        self.assertFalse(self.employee.version_id.contract_date_end)
        self.assertFalse(payslip.uae_end_of_service_id)
        self.assertEqual(eos.state, 'cancel')

    def test_no_gratuity_on_normal_payslip(self):
        payslip = self._payslip(fields.Date.today() + relativedelta(months=1, day=1))
        self.assertFalse(payslip.line_ids.filtered(lambda l: l.code in ('UAEGRAT', 'EOS', 'UAELEAVEPAY', 'UAELEAVEDED')))
