from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.hr_employee_portal.models.hr_employee import PAYSLIP_STATES

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'


class EmployeePortalCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'EP Test Company'})
        # Mon-Fri, 8 hours a day.
        cls.calendar = cls.env['resource.calendar'].create({'name': 'EP 40h', 'company_id': cls.company.id})
        cls.user_a = new_test_user(cls.env, login='ep_user_a', groups='base.group_portal',
                                   company_id=cls.company.id, company_ids=cls.company.ids)
        cls.user_b = new_test_user(cls.env, login='ep_user_b', groups='base.group_portal',
                                   company_id=cls.company.id, company_ids=cls.company.ids)
        cls.employee_a, cls.employee_b = cls.env['hr.employee'].create([{
            'name': name, 'user_id': user.id, 'company_id': cls.company.id,
            'resource_calendar_id': cls.calendar.id,
        } for name, user in (('Employee A', cls.user_a), ('Employee B', cls.user_b))])

        LeaveType = cls.env['hr.leave.type']
        cls.type_sick = LeaveType.create({
            'name': 'EP Sick', 'company_id': cls.company.id, 'requires_allocation': False,
            'leave_validation_type': 'hr', 'ep_portal_available': True,
        })
        cls.type_annual = LeaveType.create({
            'name': 'EP Annual', 'company_id': cls.company.id, 'requires_allocation': True,
            'leave_validation_type': 'hr', 'ep_portal_available': True,
        })
        cls.type_hidden = LeaveType.create({
            'name': 'EP HR only', 'company_id': cls.company.id, 'requires_allocation': False,
            'leave_validation_type': 'hr',
        })
        cls.type_auto = LeaveType.create({
            'name': 'EP No approval', 'company_id': cls.company.id, 'requires_allocation': False,
            'leave_validation_type': 'no_validation',
        })

        # A Monday at least a week ahead, so every test day is a working day.
        today = fields.Date.today()
        cls.monday = today + timedelta(days=7 - today.weekday() + 7)

    @classmethod
    def _allocate(cls, employee, days):
        allocation = cls.env['hr.leave.allocation'].create({
            'employee_id': employee.id,
            'holiday_status_id': cls.type_annual.id,
            'number_of_days': days,
            'date_from': fields.Date.today() - timedelta(days=30),
            'allocation_type': 'regular',
        })
        allocation.action_approve()
        return allocation

    def _request(self, employee, leave_type, start, end, **kw):
        return employee.sudo()._ep_create_leave_request(leave_type, start, end, **kw)


@tagged('post_install', '-at_install')
class TestEmployeePortalLeave(EmployeePortalCommon):

    def test_portal_type_needs_approval(self):
        """A type without approval cannot be offered: employees would approve their own leave."""
        with self.assertRaises(ValidationError):
            self.type_auto.ep_portal_available = True
        with self.assertRaises(ValidationError):
            self.type_hidden.write({'ep_portal_available': True, 'leave_validation_type': 'no_validation'})
        self.type_sick.leave_validation_type = 'no_validation'
        self.assertFalse(self.type_sick.ep_portal_available, "Taken out of the portal")

    def test_portal_leave_types(self):
        types = self.employee_a._ep_portal_leave_types()
        self.assertIn(self.type_sick, types)
        self.assertNotIn(self.type_hidden, types, "Not ticked for the portal")
        self.assertNotIn(self.type_auto, types, "No approval")
        self.assertNotIn(self.type_annual, types, "Needs an allocation the employee does not have")
        self._allocate(self.employee_a, 10)
        self.assertIn(self.type_annual, self.employee_a._ep_portal_leave_types())
        self.assertNotIn(self.type_annual, self.employee_b._ep_portal_leave_types())

    def test_request_waits_for_approval(self):
        leave = self._request(self.employee_a, self.type_sick, self.monday, self.monday + timedelta(days=1),
                              description='  Flu  ')
        self.assertEqual(leave.employee_id, self.employee_a)
        self.assertEqual(leave.state, 'confirm')
        self.assertEqual(leave.number_of_days, 2)
        self.assertEqual(leave.name, 'Flu')

    def test_request_refused_types(self):
        for leave_type in (self.type_hidden, self.type_auto, self.type_annual):
            with self.subTest(leave_type=leave_type.name), self.assertRaises(UserError):
                self._request(self.employee_a, leave_type, self.monday, self.monday)

    def test_request_past_dates(self):
        """Sick leave and absences are often entered afterwards."""
        last_monday = self.monday - timedelta(days=28)
        leave = self._request(self.employee_a, self.type_sick, last_monday, last_monday)
        self.assertEqual(leave.state, 'confirm')

    def test_request_half_day(self):
        self.type_sick.request_unit = 'half_day'
        # The last day is ignored: a half day is one day.
        leave = self._request(self.employee_a, self.type_sick, self.monday, self.monday + timedelta(days=3),
                              day_part='pm')
        self.assertEqual(leave.request_date_to, self.monday)
        self.assertEqual((leave.request_date_from_period, leave.request_date_to_period), ('pm', 'pm'))
        self.assertEqual(leave.number_of_days, 0.5)
        # Full days are still possible on a half-day type.
        leave = self._request(self.employee_a, self.type_sick, self.monday + timedelta(days=1),
                              self.monday + timedelta(days=2), day_part='full')
        self.assertEqual(leave.number_of_days, 2)

    def test_request_half_day_full_day_type(self):
        with self.assertRaises(UserError):
            self._request(self.employee_a, self.type_sick, self.monday, self.monday, day_part='am')

    def test_request_dates_order(self):
        with self.assertRaises(UserError):
            self._request(self.employee_a, self.type_sick, self.monday + timedelta(days=1), self.monday)

    def test_request_attachments(self):
        leave = self._request(self.employee_a, self.type_sick, self.monday, self.monday,
                              files=[('certificate.pdf', PDF), ('empty.pdf', b'')])
        attachments = self.env['ir.attachment'].search([('res_model', '=', 'hr.leave'), ('res_id', '=', leave.id)])
        self.assertEqual(attachments.mapped('name'), ['certificate.pdf'])
        self.assertEqual(attachments.mimetype, 'application/pdf')

    def test_request_attachment_type_by_content(self):
        """The file content decides, not its name."""
        with self.assertRaises(UserError):
            self._request(self.employee_a, self.type_sick, self.monday, self.monday,
                          files=[('certificate.pdf', b'<script>alert(1)</script>')])
        self.assertFalse(self.env['hr.leave'].search([('employee_id', '=', self.employee_a.id)]))

    def test_cancel_own_pending_request(self):
        leave = self._request(self.employee_a, self.type_sick, self.monday, self.monday)
        self.employee_a.sudo()._ep_cancel_leave_request(leave.sudo())
        self.assertEqual(leave.state, 'cancel')

    def test_cancel_refused(self):
        leave_b = self._request(self.employee_b, self.type_sick, self.monday, self.monday)
        with self.assertRaises(UserError):
            self.employee_a.sudo()._ep_cancel_leave_request(leave_b.sudo())
        leave_a = self._request(self.employee_a, self.type_sick, self.monday, self.monday)
        leave_a.action_approve()
        with self.assertRaises(UserError, msg="Approved leave goes through HR"):
            self.employee_a.sudo()._ep_cancel_leave_request(leave_a.sudo())

    def test_balances(self):
        self._allocate(self.employee_a, 10)
        taken = self._request(self.employee_a, self.type_annual, self.monday, self.monday + timedelta(days=1))
        taken.action_approve()
        self._request(self.employee_a, self.type_annual, self.monday + timedelta(days=3), self.monday + timedelta(days=3))
        balance = next(b for b in self.employee_a._ep_leave_balances() if b['type'] == self.type_annual)
        self.assertEqual(balance['allocated'], 10)
        self.assertEqual(balance['taken'], 2)
        self.assertEqual(balance['pending'], 1)
        self.assertEqual(balance['remaining'], 7, "Pending requests are already deducted")
        self.assertFalse(any(b['type'] == self.type_annual for b in self.employee_b._ep_leave_balances()))

    def test_enable_used_types(self):
        LeaveType = self.env['hr.leave.type']
        unused = LeaveType.create({'name': 'EP Unused', 'requires_allocation': False, 'leave_validation_type': 'hr'})
        used = LeaveType.create({'name': 'EP Used', 'requires_allocation': False, 'leave_validation_type': 'hr'})
        auto = LeaveType.create({'name': 'EP Used auto', 'requires_allocation': False,
                                 'leave_validation_type': 'no_validation'})
        self.env['hr.leave'].create([{
            'employee_id': self.employee_a.id, 'holiday_status_id': leave_type.id,
            'request_date_from': day, 'request_date_to': day,
        } for leave_type, day in ((used, self.monday), (auto, self.monday + timedelta(days=1)))])
        LeaveType._ep_enable_used_types()
        self.assertTrue(used.ep_portal_available)
        self.assertTrue(self.type_hidden.ep_portal_available, "Company types are enabled")
        self.assertFalse(unused.ep_portal_available)
        self.assertFalse(auto.ep_portal_available)

    def test_join_date_kept_on_renewal(self):
        employee = self.employee_a
        employee.version_id.write({'date_version': self.monday - timedelta(days=800),
                                   'contract_date_start': self.monday - timedelta(days=800),
                                   'contract_date_end': self.monday - timedelta(days=70)})
        employee.create_version({'date_version': self.monday - timedelta(days=69),
                                 'contract_date_start': self.monday - timedelta(days=69)})
        self.assertEqual(employee._ep_join_date(), self.monday - timedelta(days=800))

    def test_payslip_states_exist(self):
        if 'hr.payslip' not in self.env:
            self.skipTest("Payroll is not installed")
        states = dict(self.env['hr.payslip']._fields['state'].selection)
        self.assertLessEqual(set(PAYSLIP_STATES), set(states))


@tagged('post_install', '-at_install')
class TestEmployeePortalRoutes(HttpCase, EmployeePortalCommon):

    def test_leave_page(self):
        self.authenticate('ep_user_a', 'ep_user_a')
        response = self.url_open('/my/employee/leaves')
        self.assertEqual(response.status_code, 200)
        self.assertIn('EP Sick', response.text)
        self.assertNotIn('EP HR only', response.text)
        self.assertNotIn('EP No approval', response.text)

    def test_initials_without_photo(self):
        """No photo: the initials on yellow, not Odoo's generated letter image."""
        self.assertFalse(self.employee_a._ep_has_photo())
        self.authenticate('ep_user_a', 'ep_user_a')
        page = self.url_open('/my/employee').text
        self.assertIn('ep-initials', page)
        self.assertIn('>EA<', page)

    def test_profile_sections(self):
        """One folding section per topic with its short answer; HR sees the same without the employee's buttons."""
        self.employee_a.private_phone = '+971 50 111 2222'
        self.authenticate('ep_user_a', 'ep_user_a')
        page = self.url_open('/my/employee').text
        for key in ('personal', 'job', 'documents', 'leave'):
            self.assertIn('id="ep-sec-%s"' % key, page)
        self.assertIn('+971 50 111 2222', page)
        self.assertIn('Length of service', page)
        self.assertIn('Request leave', page)
        self.assertIn('id="ep-ask"', page, "New request menu")

        new_test_user(self.env, login='ep_sec_admin', groups='base.group_portal,hr_employee_portal.group_portal_hr_admin',
                      company_id=self.company.id, company_ids=self.company.ids)
        self.authenticate('ep_sec_admin', 'ep_sec_admin')
        page = self.url_open('/my/hr/employee/%s' % self.employee_a.id).text
        self.assertIn('id="ep-sec-leave"', page)
        self.assertIn('+971 50 111 2222', page)
        self.assertNotIn('Request leave', page)
        self.assertNotIn('id="ep-ask"', page)

    def test_message_not_from_url(self):
        """A link must not be able to show its own text on the portal."""
        self.authenticate('ep_user_a', 'ep_user_a')
        response = self.url_open('/my/employee/leaves?error=Call+this+number+now')
        self.assertNotIn('Call this number now', response.text)

    def test_request_and_cancel(self):
        self.authenticate('ep_user_a', 'ep_user_a')
        response = self.url_open('/my/employee/leaves/request', data={
            'csrf_token': http_csrf(self),
            'leave_type_id': self.type_sick.id,
            'date_from': str(self.monday),
            'date_to': str(self.monday),
        }, files={'attachments': ('note.pdf', PDF, 'application/pdf')})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Request sent', response.text)
        leave = self.env['hr.leave'].search([('employee_id', '=', self.employee_a.id)])
        self.assertEqual(leave.state, 'confirm')
        self.assertEqual(len(leave.attachment_ids), 1)

        response = self.url_open('/my/employee/leaves/%s/cancel' % leave.id, data={'csrf_token': http_csrf(self)})
        self.assertIn('Your request was cancelled', response.text)
        self.assertEqual(leave.state, 'cancel')

    def test_request_half_day_route(self):
        self.type_sick.request_unit = 'half_day'
        self.authenticate('ep_user_a', 'ep_user_a')
        page = self.url_open('/my/employee/leaves').text
        self.assertIn('data-ep-day-part', page)
        response = self.url_open('/my/employee/leaves/request', data={
            'csrf_token': http_csrf(self),
            'leave_type_id': self.type_sick.id,
            'day_part': 'am',
            'date_from': str(self.monday),
        })
        self.assertIn('Request sent', response.text)
        self.assertIn('(morning)', response.text)
        leave = self.env['hr.leave'].search([('employee_id', '=', self.employee_a.id)])
        self.assertEqual(leave.number_of_days, 0.5)

    def test_request_refused_type(self):
        self.authenticate('ep_user_a', 'ep_user_a')
        self.url_open('/my/employee/leaves/request', data={
            'csrf_token': http_csrf(self),
            'leave_type_id': self.type_auto.id,
            'date_from': str(self.monday),
            'date_to': str(self.monday),
        })
        self.assertFalse(self.env['hr.leave'].search([('employee_id', '=', self.employee_a.id)]))

    def test_cancel_other_employee(self):
        leave_b = self._request(self.employee_b, self.type_sick, self.monday, self.monday)
        self.authenticate('ep_user_a', 'ep_user_a')
        response = self.url_open('/my/employee/leaves/%s/cancel' % leave_b.id, data={'csrf_token': http_csrf(self)})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(leave_b.state, 'confirm')

    def test_admin_approve_and_refuse(self):
        """An HR admin of the portal approves and refuses from the dashboard."""
        new_test_user(self.env, login='ep_hr_admin', groups='base.group_portal,hr_employee_portal.group_portal_hr_admin',
                      company_id=self.company.id, company_ids=self.company.ids)
        to_approve = self._request(self.employee_b, self.type_sick, self.monday, self.monday)
        to_refuse = self._request(self.employee_b, self.type_sick, self.monday + timedelta(days=1), self.monday + timedelta(days=1))
        self.authenticate('ep_hr_admin', 'ep_hr_admin')
        page = self.url_open('/my/hr/dashboard').text
        self.assertIn('/my/hr/leave/%s/approve' % to_approve.id, page)
        # This admin has no employee record: the token comes from the dashboard
        csrf = page.split('name="csrf_token" value="')[1].split('"')[0]
        response = self.url_open('/my/hr/leave/%s/approve' % to_approve.id, data={'csrf_token': csrf})
        self.assertEqual(to_approve.state, 'validate')
        self.assertIn('Approved: Employee B', response.text)
        self.assertTrue(any('Approved by' in (m.body or '') for m in to_approve.message_ids))
        self.url_open('/my/hr/leave/%s/refuse' % to_refuse.id, data={'csrf_token': csrf})
        self.assertEqual(to_refuse.state, 'refuse')
        # Already handled
        response = self.url_open('/my/hr/leave/%s/refuse' % to_approve.id, data={'csrf_token': csrf})
        self.assertIn('already approved or refused', response.text)
        self.assertEqual(to_approve.state, 'validate')

    def test_admin_decision_not_own_nor_by_staff(self):
        admin = new_test_user(self.env, login='ep_hr_admin2', groups='base.group_portal,hr_employee_portal.group_portal_hr_admin',
                              company_id=self.company.id, company_ids=self.company.ids)
        self.employee_b.user_id = admin
        own = self._request(self.employee_b, self.type_sick, self.monday, self.monday)
        self.authenticate('ep_hr_admin2', 'ep_hr_admin2')
        self.assertIn('Your own request', self.url_open('/my/hr/dashboard').text)
        self.url_open('/my/hr/leave/%s/approve' % own.id, data={'csrf_token': http_csrf(self)})
        self.assertEqual(own.state, 'confirm')
        # Staff without HR rights
        self.authenticate('ep_user_a', 'ep_user_a')
        response = self.url_open('/my/hr/leave/%s/approve' % own.id, data={'csrf_token': http_csrf(self)})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(own.state, 'confirm')

    def test_admin_pages_hidden(self):
        self.authenticate('ep_user_a', 'ep_user_a')
        self.assertEqual(self.url_open('/my/hr/dashboard').status_code, 404)
        self.assertEqual(self.url_open('/my/hr/employee/%s' % self.employee_b.id).status_code, 404)

    def test_payslip_pages(self):
        if 'hr.payslip' not in self.env:
            self.skipTest("Payroll is not installed")
        start = self.monday.replace(day=1)
        slip = self.env['hr.payslip'].create({
            'name': 'EP May slip', 'employee_id': self.employee_a.id, 'company_id': self.company.id,
            'date_from': start, 'date_to': start + timedelta(days=27),
        })
        slip.write({'state': 'validated', 'done_date': fields.Datetime.now()})
        self.authenticate('ep_user_a', 'ep_user_a')
        for url in ('/my/employee', '/my/employee/payslips'):
            response = self.url_open(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn('/my/employee/payslips/%s/pdf' % slip.id, response.text, url)

    def test_payslip_of_other_employee(self):
        if 'hr.payslip' not in self.env:
            self.skipTest("Payroll is not installed")
        slip = self.env['hr.payslip'].create({
            'name': 'EP slip', 'employee_id': self.employee_b.id, 'company_id': self.company.id,
            'date_from': self.monday.replace(day=1), 'date_to': self.monday,
        })
        slip.write({'state': 'validated', 'done_date': fields.Datetime.now()})
        self.authenticate('ep_user_a', 'ep_user_a')
        self.assertEqual(self.url_open('/my/employee/payslips/%s/pdf' % slip.id).status_code, 404)


def http_csrf(case):
    """CSRF token of the session the test case is authenticated with."""
    return case.url_open('/my/employee/leaves').text.split('name="csrf_token" value="')[1].split('"')[0]
