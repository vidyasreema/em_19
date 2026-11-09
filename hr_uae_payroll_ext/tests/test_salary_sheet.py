import base64
import io

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_uae_leave_payroll import UaePayrollCommon

try:
    import openpyxl
except ImportError:
    openpyxl = None


@tagged('post_install', '-at_install')
class TestSalarySheet(UaePayrollCommon):
    """Gross salary 6,000: basic 4,000, allowances 2,000 (see UaePayrollCommon)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.month = fields.Date.today() + relativedelta(months=1, day=1)
        Department = cls.env['hr.department']
        cls.shop = Department.create({'name': 'Admin. & Shop Staff', 'company_id': cls.company.id})
        cls.butchery = Department.create({'name': 'Butchery', 'company_id': cls.company.id})
        cls.employee.write({'department_id': cls.shop.id, 'permit_no': 'WP-111', 'job_title': 'Cashier'})
        cls.butcher = cls._create_employee('Butcher B', cls.employee.contract_date_start)
        cls.butcher.write({'department_id': cls.butchery.id, 'job_title': 'Butcher'})
        cls.driver = cls._create_employee('Driver C', cls.employee.contract_date_start)
        cls.overtime = cls.env['hr.payroll.adjustment.type'].create({'name': 'Overtime pay', 'kind': 'addition'})

    def _add(self, employee, kind, amount):
        adjustment_type = kind if not isinstance(kind, str) else self.env.ref('hr_uae_payroll_ext.adjustment_type_%s' % kind)
        adjustment = self.env['hr.payroll.adjustment'].create({
            'employee_id': employee.id, 'type_id': adjustment_type.id, 'amount': amount,
            'date': self.month + relativedelta(days=4), 'reason': 'Test',
        })
        adjustment.action_approve()

    def _slip(self, employee):
        slip = self.env['hr.payslip'].create({
            'name': 'Sheet test', 'employee_id': employee.id, 'version_id': employee.version_id.id,
            'struct_id': self.structure.id, 'date_from': self.month, 'date_to': self.month + relativedelta(day=31),
        })
        slip.compute_sheet()
        return slip

    def _sheet(self, **values):
        return self.env['hr.payroll.salary.sheet'].create({
            'date_from': self.month, 'date_to': self.month + relativedelta(day=31), 'company_id': self.company.id,
            **values,
        })

    def test_sheet_data(self):
        self._add(self.employee, 'arrear', 1000)
        self._add(self.employee, 'commission', 750)
        self._add(self.employee, 'fine', 100)
        self._add(self.butcher, self.overtime, 300)
        self._add(self.butcher, 'deduction', 50)
        slips = self._slip(self.employee) | self._slip(self.butcher) | self._slip(self.driver)
        slips[0].action_payslip_done()

        data = self._sheet()._uae_sheet_data()
        self.assertEqual([g['name'] for g in data['groups']], ['Admin. & Shop Staff', 'Butchery', 'No Department'])
        additions = dict(data['additions'])
        self.assertEqual(list(additions)[:6], ['UAEARREAR', 'UAECOMMISSION', 'UAEGRAT', 'BONUS', 'UAELEAVEPAY', 'LOAN_PAID'])
        self.assertEqual(additions['OVERTIME_PAY'], 'Overtime pay', "A new type gets its own column")
        self.assertIn('OTHER_DEDUCTIONS', dict(data['deductions']))

        cashier = data['groups'][0]['rows'][0]
        self.assertEqual((cashier['permit'], cashier['name'], cashier['designation']), ('WP-111', self.employee.name, 'Cashier'))
        self.assertEqual((cashier['basic'], cashier['allowances']), (4000, 2000))
        self.assertEqual(cashier['additions'], {'UAEARREAR': 1000, 'UAECOMMISSION': 750})
        self.assertEqual(cashier['deductions'], {'UAEFINE': 100})
        butcher = data['groups'][1]['rows'][0]
        self.assertIn('(draft)', butcher['name'])
        self.assertEqual(butcher['additions'], {'OVERTIME_PAY': 300})
        self.assertEqual(butcher['deductions'], {'OTHER_DEDUCTIONS': 50})
        for group in data['groups']:
            for row in group['rows']:
                self.assertAlmostEqual(
                    row['basic'] + row['allowances'] + sum(row['additions'].values()) - sum(row['deductions'].values()),
                    row['net'], msg="Every amount of the payslip is in a column")

        confirmed = self._sheet(include_draft=False)._uae_sheet_data()
        self.assertEqual([g['name'] for g in confirmed['groups']], ['Admin. & Shop Staff'])

    def test_excel_file(self):
        self._add(self.employee, 'commission', 750)
        self._slip(self.employee)
        self._slip(self.butcher)
        sheet = self._sheet()
        action = sheet.action_download()
        self.assertIn('/web/content/hr.payroll.salary.sheet/%s/file/' % sheet.id, action['url'])
        self.assertTrue(sheet.file_name.endswith('.xlsx'))
        if not openpyxl:
            return
        book = openpyxl.load_workbook(io.BytesIO(base64.b64decode(sheet.file)))
        cells = [str(c.value) for row in book.active.iter_rows() for c in row if c.value is not None]
        self.assertIn(self.company.name.upper(), cells)
        self.assertIn('Admin. & Shop Staff', cells)
        self.assertIn('Commission', cells)
        self.assertIn('Sub total', cells)
        self.assertIn('Grand total', cells)
        self.assertTrue(any(c.startswith('Salaries for the Month of') for c in cells))

    def test_no_payslips(self):
        with self.assertRaises(UserError):
            self._sheet(date_from=self.month + relativedelta(years=2), date_to=self.month + relativedelta(years=2, day=31)).action_download()
