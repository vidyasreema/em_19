from odoo.exceptions import UserError
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.hr_employee_portal.tests.test_employee_portal import PDF, EmployeePortalCommon, http_csrf


class PortalRequestsCommon(EmployeePortalCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approver = new_test_user(cls.env, login='ep_req_approver', groups='base.group_user',
                                     company_id=cls.company.id, company_ids=cls.company.ids)
        Category = cls.env['approval.category']
        cls.letter = Category.create({
            'name': 'EP Salary certificate', 'company_id': cls.company.id, 'ep_portal_available': True,
            'approver_ids': [(0, 0, {'user_id': cls.approver.id})],
        })
        cls.expense = Category.create({
            'name': 'EP Expense claim', 'company_id': cls.company.id, 'ep_portal_available': True,
            'has_amount': 'required', 'has_date': 'required', 'requirer_document': 'required',
            'approver_ids': [(0, 0, {'user_id': cls.approver.id})],
        })
        cls.backend_only = Category.create({
            'name': 'EP Backend only', 'company_id': cls.company.id,
            'approver_ids': [(0, 0, {'user_id': cls.approver.id})],
        })
        cls.no_approver = Category.create({
            'name': 'EP No approver', 'company_id': cls.company.id, 'ep_portal_available': True,
        })

    def _raise(self, employee, category, files=(), **values):
        """As the employee, like the portal does."""
        return employee.with_user(employee.user_id).sudo()._ep_create_approval_request(category, values, files)


@tagged('post_install', '-at_install')
class TestPortalRequests(PortalRequestsCommon):

    def test_categories(self):
        categories = self.employee_a._ep_request_categories()
        self.assertIn(self.letter, categories)
        self.assertIn(self.expense, categories)
        self.assertNotIn(self.backend_only, categories)
        other = self.env['approval.category'].create({'name': 'EP Other company', 'ep_portal_available': True})
        self.assertNotIn(other, categories)
        with self.assertRaises(UserError):
            self._raise(self.employee_a, self.backend_only)

    def test_raise_request(self):
        approval = self._raise(self.employee_a, self.letter, subject='For the bank', reason='Addressed to ADCB')
        self.assertEqual(approval.request_status, 'pending')
        self.assertEqual(approval.request_owner_id, self.user_a)
        self.assertEqual(approval.ep_employee_id, self.employee_a)
        self.assertEqual(approval.name, 'For the bank')
        self.assertIn('ADCB', approval.reason)
        self.assertEqual(approval.approver_ids.user_id, self.approver)
        self.assertEqual(self.employee_a._ep_approval_requests(), approval)
        self.assertFalse(self.employee_b._ep_approval_requests())
        self.assertEqual(self._raise(self.employee_a, self.letter).name, self.letter.name, "Subject defaults to the kind")

    def test_required_fields(self):
        with self.assertRaisesRegex(UserError, 'amount'):
            self._raise(self.employee_a, self.expense, files=[('r.pdf', PDF)], date=self.monday)
        with self.assertRaisesRegex(UserError, 'supporting document'):
            self._raise(self.employee_a, self.expense, date=self.monday, amount=120.5)
        approval = self._raise(self.employee_a, self.expense, files=[('receipt.pdf', PDF)], date=self.monday, amount=120.5)
        self.assertEqual(approval.amount, 120.5)
        self.assertTrue(approval.date)
        self.assertEqual(approval._ep_own_attachments().mapped('name'), ['receipt.pdf'])
        self.assertFalse(approval._ep_reply_attachments())

    def test_no_approver(self):
        with self.assertRaisesRegex(UserError, 'no approver'):
            self._raise(self.employee_a, self.no_approver)

    def test_cancel(self):
        approval = self._raise(self.employee_a, self.letter)
        with self.assertRaises(UserError):
            self.employee_b.sudo()._ep_cancel_approval_request(approval)
        self.employee_a.sudo()._ep_cancel_approval_request(approval)
        self.assertEqual(approval.request_status, 'cancel')
        with self.assertRaises(UserError):
            self.employee_a.sudo()._ep_cancel_approval_request(approval)

    def test_portal_decide(self):
        hr = new_test_user(self.env, login='ep_req_hr', groups='base.group_portal,hr_employee_portal.group_portal_hr_admin',
                           company_id=self.company.id, company_ids=self.company.ids)
        approval = self._raise(self.employee_a, self.letter)
        reply = self.employee_a._ep_prepare_attachments([('certificate.pdf', PDF)])
        approval.with_user(hr).sudo()._ep_portal_decide('approve', hr, 'Collect the original at reception.', reply)
        self.assertEqual(approval.request_status, 'approved')
        self.assertEqual(approval.ep_hr_note, 'Collect the original at reception.')
        self.assertEqual(approval._ep_reply_attachments().mapped('name'), ['certificate.pdf'])
        self.assertTrue(any('Approved by' in (m.body or '') for m in approval.message_ids))
        with self.assertRaisesRegex(UserError, 'already'):
            approval.sudo()._ep_portal_decide('refuse', hr)

        refused = self._raise(self.employee_a, self.letter)
        refused.sudo()._ep_portal_decide('refuse', hr)
        self.assertEqual(refused.request_status, 'refused')
        own = self._raise(self.employee_a, self.letter)
        with self.assertRaisesRegex(UserError, 'your own'):
            own.sudo()._ep_portal_decide('approve', self.user_a)


@tagged('post_install', '-at_install')
class TestPortalRequestsRoutes(HttpCase, PortalRequestsCommon):

    def test_request_pages(self):
        self.authenticate('ep_user_a', 'ep_user_a')
        profile = self.url_open('/my/employee').text
        self.assertIn('No requests yet', profile)
        self.assertIn('/my/employee/requests/new/%s' % self.letter.id, profile, "In the New request menu")
        page = self.url_open('/my/employee/requests').text
        self.assertIn('EP Expense claim', page)
        self.assertIn('/my/employee/requests/new/%s' % self.letter.id, page)
        self.assertNotIn('/my/employee/requests/new/%s' % self.backend_only.id, page)
        form = self.url_open('/my/employee/requests/new/%s' % self.expense.id).text
        self.assertIn('name="amount"', form)
        self.assertEqual(self.url_open('/my/employee/requests/new/%s' % self.backend_only.id).status_code, 404)

        response = self.url_open('/my/employee/requests/new/%s/submit' % self.expense.id, data={
            'csrf_token': http_csrf(self), 'date': str(self.monday), 'amount': '75', 'reason': 'Taxi to the supplier',
        }, files={'attachments': ('taxi.pdf', PDF, 'application/pdf')})
        self.assertIn('Request sent', response.text)
        approval = self.employee_a._ep_approval_requests()
        self.assertEqual(approval.amount, 75)
        profile = self.url_open('/my/employee').text
        self.assertIn('EP Expense claim', profile, "Latest requests on the profile")
        self.assertIn('1 waiting for HR', profile)
        self.assertEqual(approval.request_status, 'pending')
        file_url = '/my/employee/requests/file/%s' % approval._ep_own_attachments().id
        self.assertEqual(self.url_open(file_url).content, PDF)

        # Missing required field: back to the form with a message
        response = self.url_open('/my/employee/requests/new/%s/submit' % self.expense.id, data={
            'csrf_token': http_csrf(self), 'date': str(self.monday)})
        self.assertIn('Please fill in', response.text)

        self.url_open('/my/employee/requests/%s/cancel' % approval.id, data={'csrf_token': http_csrf(self)})
        self.assertEqual(approval.request_status, 'cancel')

        self.authenticate('ep_user_b', 'ep_user_b')
        self.assertEqual(self.url_open(file_url).status_code, 404)
        response = self.url_open('/my/employee/requests/%s/cancel' % approval.id, data={'csrf_token': http_csrf(self)})
        self.assertEqual(response.status_code, 404)

    def test_admin_review(self):
        new_test_user(self.env, login='ep_req_admin', groups='base.group_portal,hr_employee_portal.group_portal_hr_admin',
                      company_id=self.company.id, company_ids=self.company.ids)
        approval = self._raise(self.employee_b, self.letter, reason='For my visa')
        to_refuse = self._raise(self.employee_b, self.letter)
        self.authenticate('ep_req_admin', 'ep_req_admin')
        page = self.url_open('/my/hr/dashboard').text
        self.assertIn('Requests to review', page)
        self.assertIn('For my visa', page)
        csrf = page.split('name="csrf_token" value="')[1].split('"')[0]
        response = self.url_open('/my/hr/request/%s/approve' % approval.id, data={
            'csrf_token': csrf, 'note': 'Ready at reception',
        }, files={'attachments': ('certificate.pdf', PDF, 'application/pdf')})
        self.assertIn('Approved: Employee B', response.text)
        self.assertEqual(approval.request_status, 'approved')
        self.url_open('/my/hr/request/%s/refuse' % to_refuse.id, data={'csrf_token': csrf})
        self.assertEqual(to_refuse.request_status, 'refused')

        # The employee sees the answer and downloads the reply
        self.authenticate('ep_user_b', 'ep_user_b')
        page = self.url_open('/my/employee/requests').text
        self.assertIn('Ready at reception', page)
        reply = approval._ep_reply_attachments()
        self.assertEqual(reply.name, 'certificate.pdf')
        self.assertEqual(self.url_open('/my/employee/requests/file/%s' % reply.id).content, PDF)
        # Staff cannot decide
        response = self.url_open('/my/hr/request/%s/approve' % to_refuse.id, data={'csrf_token': http_csrf(self)})
        self.assertEqual(response.status_code, 404)
