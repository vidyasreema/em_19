from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged

from .test_uae_leave_payroll import UaePayrollCommon


@tagged('post_install', '-at_install')
class TestAdjustmentsLoans(UaePayrollCommon):
    """Gross salary 6,000 (see UaePayrollCommon)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login='uae_payroll_manager',
            groups='base.group_user,hr_payroll.group_hr_payroll_manager',
            company_id=cls.company.id, company_ids=cls.company.ids)
        cls.officer = new_test_user(
            cls.env, login='uae_payroll_officer',
            groups='base.group_user,hr_payroll.group_hr_payroll_user',
            company_id=cls.company.id, company_ids=cls.company.ids)
        cls.month = fields.Date.today() + relativedelta(months=1, day=1)
        cls.next_month = cls.month + relativedelta(months=1)

    def _adjustment(self, kind, amount, date=None, approve=True):
        """kind: bonus, arrear, commission, addition, fine, deduction (starter types) or a type record."""
        adjustment_type = kind if not isinstance(kind, str) else self.env.ref('hr_uae_payroll_ext.adjustment_type_%s' % kind)
        adjustment = self.env['hr.payroll.adjustment'].with_user(self.officer).create({
            'employee_id': self.employee.id,
            'type_id': adjustment_type.id,
            'amount': amount,
            'date': date or self.month + relativedelta(days=4),
            'reason': 'Test',
        })
        adjustment.action_submit()
        if approve:
            adjustment.with_user(self.manager).action_approve()
        return adjustment

    def _loan(self, amount, installments, loan_type='loan', approve=True):
        loan = self.env['hr.employee.loan'].with_user(self.officer).create({
            'employee_id': self.employee.id,
            'loan_type': loan_type,
            'amount': amount,
            'installment_count': installments,
            'first_deduction_date': self.month,
            'reason': 'Test',
        })
        if approve:
            loan.with_user(self.manager).action_approve()
        return loan

    # ------------------------------------------------------------------
    # Additions and deductions
    # ------------------------------------------------------------------

    def test_sequence_and_approval_activity(self):
        adjustment = self._adjustment('bonus', 500, approve=False)
        self.assertTrue(adjustment.name.startswith('ADJ/'))
        self.assertEqual(adjustment.state, 'to_approve')
        self.assertIn(self.manager, adjustment.activity_ids.user_id)
        adjustment.with_user(self.manager).action_approve()
        self.assertEqual(adjustment.state, 'approved')
        self.assertFalse(adjustment.activity_ids)

    def test_only_manager_approves(self):
        adjustment = self._adjustment('bonus', 500, approve=False)
        with self.assertRaises(UserError):
            adjustment.with_user(self.officer).action_approve()

    def test_approved_records_in_payslip(self):
        self._adjustment('bonus', 500)
        self._adjustment('fine', 100)
        self._adjustment('deduction', 50)
        self._adjustment('addition', 25, approve=False)  # not approved: left out
        payslip = self._payslip(self.month)
        self.assertAlmostEqual(self._line_total(payslip, 'BONUS'), 500)
        self.assertAlmostEqual(self._line_total(payslip, 'UAEFINE'), -100)
        self.assertAlmostEqual(self._line_total(payslip, 'OTHER_DEDUCTIONS'), -50)
        self.assertFalse(self._line_total(payslip, 'OTHER_EARNINGS'))

    def test_each_type_its_own_line(self):
        """Arrear salary and commission are additions with their own payslip line, named after the type."""
        self._adjustment('arrear', 1000)
        self._adjustment('commission', 750)
        self._adjustment('bonus', 200)
        self._adjustment('bonus', 300)
        payslip = self._payslip(self.month)
        self.assertAlmostEqual(self._line_total(payslip, 'UAEARREAR'), 1000)
        self.assertAlmostEqual(self._line_total(payslip, 'UAECOMMISSION'), 750)
        self.assertAlmostEqual(self._line_total(payslip, 'BONUS'), 500, "Two bonuses, one line")
        names = dict((line.code, line.name) for line in payslip.line_ids)
        self.assertEqual(names['UAEARREAR'], 'Arrear Salary')
        self.assertEqual(names['BONUS'], 'Bonus')
        self.assertAlmostEqual(payslip.net_wage, 6000 + 1000 + 750 + 500)

    def test_new_type(self):
        """A type made by HR gets its payslip input and line in the monthly structure."""
        Type = self.env['hr.payroll.adjustment.type'].with_user(self.manager)
        overtime = Type.create({'name': 'Overtime pay', 'kind': 'addition'})
        damage = Type.create({'name': 'Damaged stock', 'kind': 'deduction'})
        self.assertEqual(overtime.code, 'OVERTIME_PAY')
        self.assertEqual(overtime.rule_id.struct_id, self.structure)
        self.assertEqual(damage.rule_id.category_id, self.env.ref('hr_payroll.DED'))
        self.assertEqual(Type.create({'name': 'Overtime pay!', 'kind': 'addition'}).code, 'OVERTIME_PAY_2')
        self._adjustment(overtime, 400)
        self._adjustment(damage, 150)
        payslip = self._payslip(self.month)
        self.assertAlmostEqual(self._line_total(payslip, 'OVERTIME_PAY'), 400)
        self.assertAlmostEqual(self._line_total(payslip, 'DAMAGED_STOCK'), -150)

        overtime.name = 'Overtime'
        self.assertEqual(overtime.rule_id.name, 'Overtime')
        with self.assertRaises(UserError):
            overtime.write({'kind': 'deduction'})
        with self.assertRaises(UserError):
            overtime.write({'code': 'OT'})
        with self.assertRaises(UserError):
            overtime.unlink()
        with self.assertRaises(AccessError):
            self.env['hr.payroll.adjustment.type'].with_user(self.officer).create({'name': 'Tips'})

    def test_validated_payslip_marks_paid(self):
        bonus = self._adjustment('bonus', 500)
        payslip = self._payslip(self.month)
        payslip.action_payslip_done()
        self.assertEqual(bonus.state, 'paid')
        self.assertEqual(bonus.payslip_id, payslip)
        # Paid once only: not in the next payslip.
        self.assertFalse(self._line_total(self._payslip(self.next_month), 'BONUS'))
        payslip.action_payslip_cancel()
        self.assertEqual(bonus.state, 'approved')
        self.assertFalse(bonus.payslip_id)

    def test_late_adjustment_in_next_payslip(self):
        # Dated last month, approved now: goes to this month's payslip.
        self._adjustment('fine', 100, date=self.month - relativedelta(days=5))
        self.assertAlmostEqual(self._line_total(self._payslip(self.month), 'UAEFINE'), -100)

    def test_adjustment_after_compute_needs_recompute(self):
        payslip = self._payslip(self.month)
        self._adjustment('bonus', 300)
        payslip.compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'BONUS'), 300)

    def test_fine_warning(self):
        # 5 days of 6,000 / 30 = 1,000.
        self.assertFalse(self._adjustment('fine', 600).fine_warning)
        self.assertTrue(self._adjustment('fine', 600).fine_warning)

    # ------------------------------------------------------------------
    # Loans and advances
    # ------------------------------------------------------------------

    def test_loan_schedule_and_recovery(self):
        loan = self._loan(3000, 6)
        self.assertTrue(loan.name.startswith('LOAN/'))
        self.assertEqual(loan.state, 'running')
        self.assertEqual(loan.line_ids.mapped('amount'), [500] * 6)
        self.assertEqual(loan.line_ids[0].date, self.month)

        payslip = self._payslip(self.month)
        self.assertAlmostEqual(self._line_total(payslip, 'UAELOAN'), -500)
        self.assertEqual(loan.remaining_amount, 3000, "Recovered once the payslip is validated")
        payslip.action_payslip_done()
        self.assertEqual(loan.paid_amount, 500)
        self.assertEqual(loan.remaining_amount, 2500)
        self.assertTrue(loan.line_ids[0].is_recovered)
        self.assertFalse(loan.line_ids[1].is_recovered)
        self.assertAlmostEqual(self._line_total(self._payslip(self.next_month), 'UAELOAN'), -500)

    def test_printed_payslip(self):
        self._adjustment('commission', 750)
        self._adjustment('fine', 100)
        loan = self._loan(3000, 6)
        monday = self.month + relativedelta(weekday=0)
        self._leave(self.unpaid, monday, monday + relativedelta(days=1))
        payslip = self._payslip(self.month)
        payslip.action_payslip_done()

        values = payslip._uae_report_values()
        earnings = {row['name']: row for row in values['earnings']}
        deductions = {row['name']: row for row in values['deductions']}
        self.assertEqual(list(earnings)[0], 'Basic Salary')
        self.assertEqual(earnings['Commission']['amount'], 750)
        self.assertEqual(earnings['Commission']['detail'], 'Test', "The reason is shown under the line")
        self.assertEqual(deductions['Fine']['amount'], 100, "Deductions are shown as positive amounts")
        self.assertEqual(deductions['Unpaid Leave']['detail'], '2 days')
        self.assertIn('%s: balance after this payslip' % loan.name, deductions['Loan Recovery']['detail'])
        self.assertIn('2,500.00', deductions['Loan Recovery']['detail'])
        self.assertNotIn('Net Salary', earnings, "Totals are not earnings")
        self.assertAlmostEqual(values['total_earnings'] - values['total_deductions'], payslip.net_wage)

        report = self.env.ref('hr_uae_payroll_ext.action_report_payslip_uae')
        self.assertEqual(self.structure.report_id, report)
        html = self.env['ir.actions.report']._render_qweb_html(report, payslip.ids)[0].decode()
        for text in ('Earnings', 'Deductions', 'Total earnings', 'NET SALARY', 'balance after this payslip'):
            self.assertIn(text, html)

    def test_uneven_schedule(self):
        loan = self._loan(1000, 3)
        self.assertEqual(loan.line_ids.mapped('amount'), [333.33, 333.33, 333.34])

    def test_deduction_cap(self):
        # Cap 20% of 6,000 = 1,200 a month; 3,000 due in the first month.
        loan = self._loan(6000, 2)
        payslip = self._payslip(self.month)
        self.assertAlmostEqual(self._line_total(payslip, 'UAELOAN'), -1200)
        payslip.action_payslip_done()
        # Next month: 6,000 due in total, 1,200 recovered: still capped.
        self.assertAlmostEqual(self._line_total(self._payslip(self.next_month), 'UAELOAN'), -1200)
        self.company.uae_loan_deduction_cap = 0
        self.assertAlmostEqual(self._line_total(self._payslip(self.next_month), 'UAELOAN'), -4800)
        self.assertEqual(loan.remaining_amount, 4800)

    def test_salary_advance_closes(self):
        advance = self._loan(1000, 5, loan_type='advance')
        self.assertEqual(advance.installment_count, 1, "An advance is recovered in one go")
        payslip = self._payslip(self.month)
        self.assertAlmostEqual(self._line_total(payslip, 'UAEADVANCE'), -1000)
        self.assertFalse(self._line_total(payslip, 'UAELOAN'), "An advance has its own payslip line")
        payslip.action_payslip_done()
        self.assertEqual(advance.state, 'closed')
        payslip.action_payslip_cancel()
        self.assertEqual(advance.state, 'running')

    def test_loan_and_advance_lines(self):
        # Cap 20% of 6,000 = 1,200 for both: the loan instalment, then what is left for the advance.
        self._loan(3000, 6)
        advance = self._loan(1000, 1, loan_type='advance')
        payslip = self._payslip(self.month)
        self.assertAlmostEqual(self._line_total(payslip, 'UAELOAN'), -500)
        self.assertAlmostEqual(self._line_total(payslip, 'UAEADVANCE'), -700)
        payslip.action_payslip_done()
        self.assertEqual(advance.remaining_amount, 300)
        next_payslip = self._payslip(self.next_month)
        self.assertAlmostEqual(self._line_total(next_payslip, 'UAELOAN'), -500)
        self.assertAlmostEqual(self._line_total(next_payslip, 'UAEADVANCE'), -300)

    def test_loan_limits(self):
        # 2 months of 6,000 at most, 12 instalments at most.
        loan = self._loan(20000, 10, approve=False)
        self.assertTrue(loan.limit_warning)
        with self.assertRaises(UserError):
            loan.action_submit()
        # A manager can still approve it.
        loan.with_user(self.manager).action_approve()
        self.assertEqual(loan.state, 'running')
        self.assertFalse(self._loan(12000, 12, approve=False).limit_warning)
        self.assertTrue(self._loan(1000, 13, approve=False).limit_warning)

    def test_refuse_after_recovery(self):
        loan = self._loan(1000, 2)
        self._payslip(self.month).action_payslip_done()
        with self.assertRaises(UserError):
            loan.with_user(self.manager).action_refuse()

    def test_running_loan_not_deleted(self):
        loan = self._loan(1000, 2)
        with self.assertRaises(UserError):
            loan.unlink()
