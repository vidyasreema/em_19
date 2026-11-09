from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.hr_employee_portal.tests.test_employee_portal import PDF, EmployeePortalCommon, http_csrf


class PortalDocumentsCommon(EmployeePortalCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.passport = cls.env.ref('hr_employee_portal_documents.doc_type_passport')
        cls.work_permit = cls.env.ref('hr_employee_portal_documents.doc_type_work_permit')
        cls.education = cls.env.ref('hr_employee_portal_documents.doc_type_education')
        cls.next_year = fields.Date.today() + timedelta(days=365)

    def _upload(self, employee, doc_type, number='', expiry=None, files=(('scan.pdf', PDF),), note=''):
        """As the employee, like the portal does."""
        return employee.with_user(employee.user_id).sudo()._ep_upload_document(doc_type, number, expiry, note, files)

    def _line(self, employee, doc_type):
        return next(line for line in employee._ep_document_checklist() if line['type'] == doc_type)


@tagged('post_install', '-at_install')
class TestPortalDocuments(PortalDocumentsCommon):

    def test_default_types_linked(self):
        """On install, the starter types point at the employee fields of the database."""
        self.assertEqual(self.passport.number_field_id.name, 'passport_id')
        self.assertIn(self.passport.expiry_field_id.name,
                      ('x_studio_passport_expiration_date', 'passport_expiration_date'))
        self.assertEqual(self.work_permit.number_field_id.name, 'permit_no')
        self.assertEqual(self.work_permit.file_field_id.name, 'has_work_permit')
        self.assertFalse(self.education.file_field_id)

    def test_new_employee_checklist(self):
        lines = self.employee_a._ep_document_checklist()
        self.assertTrue(lines)
        self.assertEqual({line['status'] for line in lines}, {'missing'})
        to_upload = [line['type'] for line in self.employee_a._ep_documents_to_upload()]
        self.assertIn(self.passport, to_upload)
        self.assertNotIn(self.education, to_upload, "Optional documents are not asked for")

    def test_upload_and_verify(self):
        first = self._upload(self.employee_a, self.passport, 'P123', self.next_year)
        self.assertEqual(first.state, 'pending')
        self.assertEqual(first.attachment_ids.mapped('name'), ['scan.pdf'])
        self.assertEqual(self._line(self.employee_a, self.passport)['status'], 'pending')
        self.assertNotIn(self.passport, [l['type'] for l in self.employee_a._ep_documents_to_upload()])

        second = self._upload(self.employee_a, self.passport, 'P456', self.next_year, note='Renewed last week')
        self.assertEqual(first.state, 'cancel', "A newer upload replaces the one still waiting")
        self.assertEqual(second.employee_note, 'Renewed last week')

        second = second.with_env(self.env)  # HR checks it in the backend
        second.action_verify()
        self.assertEqual(second.state, 'verified')
        self.assertEqual(second.checked_by_id, self.env.user)
        self.assertEqual(self.employee_a.passport_id, 'P456')
        self.assertEqual(self.employee_a[self.passport.expiry_field_id.name], self.next_year)
        line = self._line(self.employee_a, self.passport)
        self.assertEqual((line['status'], line['number']), ('on_file', 'P456'))
        self.assertTrue(any('verified' in (m.body or '') for m in self.employee_a.message_ids))
        with self.assertRaisesRegex(UserError, 'already checked'):
            second.action_verify()

    def test_verify_copies_file(self):
        document = self._upload(self.employee_a, self.work_permit, 'WP-1', self.next_year)
        document.action_verify()
        self.assertEqual(self.employee_a.permit_no, 'WP-1')
        self.assertTrue(self.employee_a.has_work_permit)

    def test_upload_checks(self):
        with self.assertRaisesRegex(UserError, 'document number'):
            self._upload(self.employee_a, self.passport, '', self.next_year)
        with self.assertRaisesRegex(UserError, 'file'):
            self._upload(self.employee_a, self.passport, 'P1', self.next_year, files=())
        with self.assertRaisesRegex(UserError, 'expired'):
            self._upload(self.employee_a, self.passport, 'P1', fields.Date.today() - timedelta(days=1))
        with self.assertRaisesRegex(UserError, 'not a PDF'):
            self._upload(self.employee_a, self.passport, 'P1', self.next_year, files=[('x.pdf', b'hello')])
        archived = self.education.copy({'active': False})
        with self.assertRaises(UserError):
            self._upload(self.employee_a, archived)
        self.assertFalse(self.env['hr.employee.document'].search([('employee_id', '=', self.employee_a.id)]))
        # Optional fields stay optional
        self.assertTrue(self._upload(self.employee_a, self.education))

    def test_reject(self):
        document = self._upload(self.employee_a, self.passport, 'P1', self.next_year)
        with self.assertRaisesRegex(UserError, 'note'):
            document.action_reject()
        document.hr_note = 'The scan is blurred'
        document.action_reject()
        line = self._line(self.employee_a, self.passport)
        self.assertEqual(line['status'], 'rejected')
        self.assertEqual(line['upload'].hr_note, 'The scan is blurred')
        self.assertIn(self.passport, [l['type'] for l in self.employee_a._ep_documents_to_upload()])
        self.assertFalse(self.employee_a.passport_id, "Nothing goes into the profile")

    def test_entered_by_hr(self):
        """Documents HR already keeps on the profile are not asked again."""
        self.employee_a.passport_id = 'HR-1'
        self.assertEqual(self._line(self.employee_a, self.passport)['status'], 'on_file')
        self.assertNotIn(self.passport, [l['type'] for l in self.employee_a._ep_documents_to_upload()])

    def test_portal_decide(self):
        hr = new_test_user(self.env, login='ep_doc_hr', groups='base.group_portal,hr_employee_portal.group_portal_hr_admin',
                           company_id=self.company.id, company_ids=self.company.ids)
        document = self._upload(self.employee_a, self.passport, 'P9', self.next_year)
        with self.assertRaisesRegex(UserError, 'note'):
            document._ep_portal_decide('reject', hr)
        document._ep_portal_decide('verify', hr, 'Thanks')
        self.assertEqual(document.state, 'verified')
        self.assertEqual(document.checked_by_id, hr)
        self.assertEqual(self.employee_a.passport_id, 'P9')
        own = self._upload(self.employee_a, self.education)
        with self.assertRaisesRegex(UserError, 'your own'):
            own._ep_portal_decide('verify', self.user_a)


@tagged('post_install', '-at_install')
class TestPortalDocumentsRoutes(HttpCase, PortalDocumentsCommon):

    def test_documents_page(self):
        self.authenticate('ep_user_a', 'ep_user_a')
        profile = self.url_open('/my/employee').text
        self.assertIn('HR still needs', profile)
        self.assertIn('To do: Passport', profile)
        self.assertIn('Upload a document', profile)
        page = self.url_open('/my/employee/documents').text
        self.assertIn('Passport', page)
        self.assertIn('/my/employee/documents/%s/upload' % self.passport.id, page)

        response = self.url_open('/my/employee/documents/%s/upload' % self.passport.id, data={
            'csrf_token': http_csrf(self), 'number': 'P777', 'expiry': str(self.next_year),
        }, files={'attachments': ('passport.pdf', PDF, 'application/pdf')})
        self.assertIn('Passport sent', response.text)
        self.assertIn('Waiting for HR', response.text)
        profile = self.url_open('/my/employee').text
        self.assertNotIn('To do: Passport', profile, "Sent, so no longer to do")
        self.assertIn('To do: Visa', profile)
        document = self.env['hr.employee.document'].search([('employee_id', '=', self.employee_a.id)])
        self.assertEqual(document.document_number, 'P777')
        file_url = '/my/employee/documents/file/%s' % document.attachment_ids.id
        self.assertEqual(self.url_open(file_url).content, PDF)

        # Missing number: back with a message, nothing saved
        response = self.url_open('/my/employee/documents/%s/upload' % self.passport.id, data={
            'csrf_token': http_csrf(self), 'expiry': str(self.next_year),
        }, files={'attachments': ('passport.pdf', PDF, 'application/pdf')})
        self.assertIn('Please fill in', response.text)
        self.assertEqual(document.state, 'pending')

        self.authenticate('ep_user_b', 'ep_user_b')
        self.assertEqual(self.url_open(file_url).status_code, 404)

    def test_admin_check(self):
        new_test_user(self.env, login='ep_doc_admin', groups='base.group_portal,hr_employee_portal.group_portal_hr_admin',
                      company_id=self.company.id, company_ids=self.company.ids)
        to_verify = self._upload(self.employee_b, self.passport, 'P55', self.next_year, note='New passport')
        to_reject = self._upload(self.employee_b, self.work_permit, 'WP9', self.next_year)
        self.authenticate('ep_doc_admin', 'ep_doc_admin')
        page = self.url_open('/my/hr/dashboard').text
        self.assertIn('Documents to check', page)
        self.assertIn('New passport', page)
        self.assertEqual(self.url_open('/my/employee/documents/file/%s' % to_verify.attachment_ids.id).content, PDF)
        csrf = page.split('name="csrf_token" value="')[1].split('"')[0]
        response = self.url_open('/my/hr/document/%s/verify' % to_verify.id, data={'csrf_token': csrf})
        self.assertIn('Verified: Employee B', response.text)
        self.assertEqual(self.employee_b.passport_id, 'P55')

        response = self.url_open('/my/hr/document/%s/reject' % to_reject.id, data={'csrf_token': csrf})
        self.assertIn('Write a note', response.text)
        self.assertEqual(to_reject.state, 'pending')
        self.url_open('/my/hr/document/%s/reject' % to_reject.id, data={'csrf_token': csrf, 'note': 'Card is cut off'})
        self.assertEqual(to_reject.state, 'rejected')

        # The employee sees the answer
        self.authenticate('ep_user_b', 'ep_user_b')
        page = self.url_open('/my/employee/documents').text
        self.assertIn('Card is cut off', page)
        self.assertIn('Sent back', page)
        self.assertIn('On file', page)
        # Staff cannot check
        response = self.url_open('/my/hr/document/%s/verify' % to_reject.id, data={'csrf_token': http_csrf(self)})
        self.assertEqual(response.status_code, 404)
