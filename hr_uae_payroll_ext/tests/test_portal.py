from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.hr_employee_portal.tests.test_employee_portal import http_csrf

from .test_uae_leave_payroll import UaePayrollCommon


@tagged('post_install', '-at_install')
class TestUaePortal(HttpCase, UaePayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_a, cls.user_b = (new_test_user(
            cls.env, login=login, groups='base.group_portal',
            company_id=cls.company.id, company_ids=cls.company.ids) for login in ('uae_portal_a', 'uae_portal_b'))
        two_years_ago = fields.Date.today() - relativedelta(years=2)
        cls.employee_a = cls._create_employee('Portal A', two_years_ago)
        cls.employee_b = cls._create_employee('Portal B', two_years_ago)
        cls.employee_a.user_id = cls.user_a
        cls.employee_b.user_id = cls.user_b

        Loan = cls.env['hr.employee.loan']
        cls.loan_a = Loan.create({'employee_id': cls.employee_a.id, 'amount': 1200, 'installment_count': 3, 'reason': 'Car repair A'})
        cls.loan_b = Loan.create({'employee_id': cls.employee_b.id, 'amount': 900, 'installment_count': 3, 'reason': 'Rent B'})
        (cls.loan_a | cls.loan_b).action_approve()
        Adjustment = cls.env['hr.payroll.adjustment']
        cls.fine_b = Adjustment.create({
            'employee_id': cls.employee_b.id, 'type_id': cls.env.ref('hr_uae_payroll_ext.adjustment_type_fine').id,
            'amount': 75, 'reason': 'Late B',
        })
        cls.bonus_a = Adjustment.create({
            'employee_id': cls.employee_a.id, 'type_id': cls.env.ref('hr_uae_payroll_ext.adjustment_type_bonus').id,
            'amount': 250, 'reason': 'Great month A',
        })
        (cls.fine_b | cls.bonus_a).action_approve()

    def _login_a(self):
        self.authenticate('uae_portal_a', 'uae_portal_a')

    def test_pay_page_shows_own_records_only(self):
        self._login_a()
        response = self.url_open('/my/employee/pay')
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.loan_a.name, response.text)
        self.assertNotIn(self.loan_b.name, response.text)
        self.assertIn('Great month A', response.text)
        self.assertIn('Gratuity estimate', response.text)
        self.assertNotIn('Late B', response.text)
        self.assertIn('/my/employee/pay', response.text, "Navigation link")

    def test_loan_request(self):
        self._login_a()
        response = self.url_open('/my/employee/pay/loan', data={
            'csrf_token': http_csrf(self),
            'loan_type': 'loan', 'amount': '600', 'installment_count': '3', 'reason': 'School fees',
        })
        self.assertEqual(response.status_code, 200)
        loan = self.env['hr.employee.loan'].search([('employee_id', '=', self.employee_a.id), ('reason', '=', 'School fees')])
        self.assertEqual(loan.state, 'to_approve')
        self.assertEqual(loan.installment_count, 3)
        self.assertIn(loan.name, response.text)

    def test_loan_request_above_limits(self):
        # 2 months of the 6,000 gross salary at most.
        self._login_a()
        response = self.url_open('/my/employee/pay/loan', data={
            'csrf_token': http_csrf(self),
            'loan_type': 'loan', 'amount': '50000', 'installment_count': '3', 'reason': 'Too much',
        })
        self.assertIn('above what the company allows', response.text)
        self.assertFalse(self.env['hr.employee.loan'].search([('reason', '=', 'Too much')]))

    def test_settlement_pdf_access(self):
        eos_b = self.env['hr.end.of.service'].create({'employee_id': self.employee_b.id})
        eos_a = self.env['hr.end.of.service'].create({'employee_id': self.employee_a.id})
        self._login_a()
        # Not someone else's, and not before the final settlement.
        self.assertEqual(self.url_open('/my/employee/end-of-service/%s/pdf' % eos_b.id).status_code, 404)
        self.assertEqual(self.url_open('/my/employee/end-of-service/%s/pdf' % eos_a.id).status_code, 404)
        response = self.url_open('/my/employee/pay')
        self.assertIn('End of service', response.text)

    def test_attendance_page(self):
        self._login_a()
        response = self.url_open('/my/employee/attendance')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Attendance', response.text)
        self.assertIn('ep-cal-day is-', response.text)
        # Another month, a wrong month, and the old Timesheets address
        self.assertEqual(self.url_open('/my/employee/attendance?month=2025-02').status_code, 200)
        self.assertEqual(self.url_open('/my/employee/attendance?month=nonsense').status_code, 200)
        self.assertTrue(self.url_open('/my/employee/timesheets').url.endswith('/my/employee/attendance'))

    def test_profile_sections(self):
        """Salary, loans and attendance on the profile, for the employee's own records only."""
        self._login_a()
        page = self.url_open('/my/employee').text
        for key in ('pay', 'loans', 'attendance'):
            self.assertIn('id="ep-sec-%s"' % key, page)
        self.assertIn('Basic salary', page)
        self.assertIn(self.loan_a.name, page)
        self.assertNotIn(self.loan_b.name, page)
        self.assertIn('left · next', page)
        self.assertIn('present so far', page)
        self.assertIn('/my/employee/pay#ep-loan-request', page, "Loans in the New request menu")

    def test_leaver_keeps_portal(self):
        self.employee_a.with_context(no_wizard=True).action_archive()
        self._login_a()
        response = self.url_open('/my/employee/pay')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Great month A', response.text)
        self.assertNotIn('Request a loan', response.text)

    def test_record_rules(self):
        """Direct access (not through the portal pages) is limited to own records."""
        Loan = self.env['hr.employee.loan'].with_user(self.user_a)
        self.assertEqual(Loan.search([]), self.loan_a)
        self.assertEqual(self.env['hr.payroll.adjustment'].with_user(self.user_a).search([]), self.bonus_a)
        self.assertEqual(self.env['hr.employee.loan.line'].with_user(self.user_a).search([]), self.loan_a.line_ids)
