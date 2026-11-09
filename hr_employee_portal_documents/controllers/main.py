from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from odoo.addons.hr_employee_portal.controllers.main import EXPIRY_WINDOW_DAYS, EmployeePortal, _initials
from odoo.addons.hr_employee_portal.models.hr_employee import ATTACHMENT_MAX_COUNT, ATTACHMENT_MAX_SIZE


class EmployeePortalDocuments(EmployeePortal):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ep_document_files(self, document):
        return [{'id': a.id, 'name': a.name} for a in document._ep_files()]

    def _ep_document_facts(self, number, expiry):
        parts = []
        if number:
            parts.append(request.env._("No. %s", number))
        if expiry:
            parts.append(request.env._("Expires %s", self._ep_fmt_date(expiry, 'd MMM y')))
        return ' · '.join(parts)

    def _ep_document_rows(self, employee):
        """The document checklist of the portal page, with labels."""
        today = fields.Date.context_today(request.env.user)
        rows = []
        for line in employee._ep_document_checklist():
            doc_type, status, upload = line['type'], line['status'], line['upload']
            sub = self._ep_document_facts(line['number'], line['expiry'])
            files = []
            if status == 'pending':
                kind, label, action = 'wait', request.env._("Waiting for HR"), request.env._("Replace upload")
                sub = ' · '.join(filter(None, [
                    request.env._("Sent %s", self._ep_fmt_date(upload.create_date.date(), 'd MMM')),
                    self._ep_document_facts(upload.document_number, upload.expiry_date)]))
                files = self._ep_document_files(upload)
            elif status == 'rejected':
                kind, label, action = 'bad', request.env._("Sent back"), request.env._("Upload again")
            elif status == 'on_file':
                days = (line['expiry'] - today).days if line['expiry'] else None
                if days is not None and days < 0:
                    kind, label, action = 'bad', request.env._("Expired"), request.env._("Upload renewed")
                elif days is not None and days <= EXPIRY_WINDOW_DAYS:
                    kind, label, action = 'wait', request.env._("Renew soon"), request.env._("Upload renewed")
                else:
                    kind, label, action = 'ok', request.env._("On file"), request.env._("Replace")
            elif doc_type.required:
                kind, label, action = 'bad', request.env._("Missing"), request.env._("Upload")
            else:
                kind, label, action = 'muted', request.env._("Optional"), request.env._("Upload")
            rows.append({
                'type': doc_type,
                'status': status,
                'kind': kind,
                'label': label,
                'action': action,
                'sub': sub or doc_type.description or '',
                'note': upload.hr_note if status == 'rejected' else '',
                'files': files,
                'open': status == 'rejected',
            })
        return rows

    def _ep_documents_to_review(self):
        documents = request.env['hr.employee.document'].sudo().search([
            ('state', '=', 'pending'),
            ('company_id', 'in', self._ep_allowed_companies().ids),
        ], order='create_date, id')
        return [{
            'id': document.id,
            'employee': document.employee_id,
            'initials': _initials(document.employee_id.name),
            'title': document.type_id.name,
            'sub': ' · '.join(filter(None, [
                request.env._("Uploaded %s", self._ep_fmt_date(document.create_date.date(), 'd MMM')),
                self._ep_document_facts(document.document_number, document.expiry_date)])),
            'note': document.employee_note or '',
            'files': self._ep_document_files(document),
            'can_decide': document.employee_id.user_id != request.env.user,
        } for document in documents]

    # ------------------------------------------------------------------
    # Employee pages
    # ------------------------------------------------------------------

    def _ep_request_tiles(self, employee):
        tiles = super()._ep_request_tiles(employee)
        if employee._ep_document_types():
            tiles.append({'href': '/my/employee/documents', 'label': request.env._("Upload a document"),
                          'icon': 'upload', 'sub': request.env._("Passport, visa, Emirates ID and more"), 'sequence': 90})
        return tiles

    def _ep_profile_values(self, employee, **extra):
        values = super()._ep_profile_values(employee, **extra)
        rows = [r for r in self._ep_document_rows(employee) if r['kind'] != 'muted']
        values['documents_to_upload'] = [line['type'].name for line in employee._ep_documents_to_upload()]
        values['document_rows'] = rows
        if rows:
            values['summaries']['documents'] = self._ep_document_summary(rows)
        return values

    def _ep_document_summary(self, rows):
        bad = [r['type'].name for r in rows if r['kind'] == 'bad']
        if bad:
            return self._ep_summary(request.env._("To do: %s", ', '.join(bad)), 'bad')
        wait = ['%s: %s' % (r['type'].name, r['label']) for r in rows if r['kind'] == 'wait']
        if wait:
            return self._ep_summary('; '.join(wait), 'wait')
        return self._ep_summary(request.env._("All documents on file"), 'ok')

    @http.route('/my/employee/documents', type='http', auth='user', website=True)
    def ep_documents(self, **kw):
        employee = self._ep_current_employee()
        if not employee:
            return request.redirect('/my/employee')
        rows = self._ep_document_rows(employee)
        required = [r for r in rows if r['type'].required]
        return self._ep_render('hr_employee_portal_documents.ep_documents', {
            'page_name': 'ep_documents',
            'employee': employee,
            'document_rows': rows,
            'required_total': len(required),
            'required_done': len([r for r in required if r['status'] in ('on_file', 'pending')]),
            'flash': self._ep_pop_flash(),
            'today': fields.Date.context_today(request.env.user),
            'attachment_max_count': ATTACHMENT_MAX_COUNT,
            'attachment_max_mb': ATTACHMENT_MAX_SIZE // (1024 * 1024),
        })

    @http.route('/my/employee/documents/<int:type_id>/upload', type='http', auth='user',
                methods=['POST'], website=True)
    def ep_document_upload(self, type_id, number=None, expiry=None, note=None, **kw):
        employee = self._ep_current_employee()
        if not employee or not employee.active:
            return request.redirect('/my/employee')
        doc_type = request.env['hr.employee.document.type'].sudo().browse(type_id).exists()
        if doc_type not in employee._ep_document_types():
            raise NotFound()
        try:
            expiry = fields.Date.to_date(expiry or None)
        except ValueError:
            self._ep_set_flash('bad', request.env._("Check the expiry date."))
            return request.redirect('/my/employee/documents')
        files = [(f.filename, f.read()) for f in request.httprequest.files.getlist('attachments')]
        try:
            with request.env.cr.savepoint():
                employee._ep_upload_document(doc_type, number, expiry, note, files)
        except (UserError, ValidationError, AccessError) as e:
            self._ep_set_flash('bad', '%s: %s' % (doc_type.name, e.args[0] if e.args else
                                                  request.env._("the document could not be saved.")))
        else:
            self._ep_set_flash('ok', request.env._(
                "%s sent. HR will check it; you'll see the result here.", doc_type.name))
        return request.redirect('/my/employee/documents')

    @http.route('/my/employee/documents/file/<int:attachment_id>', type='http', auth='user')
    def ep_document_file(self, attachment_id, **kw):
        """A file of an upload: for its employee, or for an HR admin."""
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id).exists()
        if not attachment or attachment.res_model != 'hr.employee.document' or attachment.res_field:
            raise NotFound()
        document = request.env['hr.employee.document'].sudo().browse(attachment.res_id).exists()
        employee = self._ep_current_employee()
        allowed = document and (
            (employee and document.employee_id == employee)
            or (self._ep_is_admin() and document.company_id in self._ep_allowed_companies()))
        if not allowed:
            raise NotFound()
        return request.env['ir.binary']._get_stream_from(attachment).get_response(as_attachment=True)

    # ------------------------------------------------------------------
    # Admin pages
    # ------------------------------------------------------------------

    @http.route()
    def ep_admin_dashboard(self, q=None, department=None, **kw):
        response = super().ep_admin_dashboard(q=q, department=department, **kw)
        if hasattr(response, 'qcontext'):
            response.qcontext['document_reviews'] = self._ep_documents_to_review()
        return response

    @http.route('/my/hr/document/<int:document_id>/<string:decision>', type='http', auth='user',
                methods=['POST'], website=True)
    def ep_admin_document_decision(self, document_id, decision, note=None, **kw):
        """Verify or reject an uploaded document from the HR dashboard."""
        self._ep_require_admin()
        document = request.env['hr.employee.document'].sudo().browse(document_id).exists()
        if decision not in ('verify', 'reject') or not document \
                or document.company_id not in self._ep_allowed_companies():
            raise NotFound()
        what = '%s, %s' % (document.employee_id.name, document.type_id.name)
        try:
            with request.env.cr.savepoint():
                document._ep_portal_decide(decision, request.env.user, note)
        except (UserError, ValidationError, AccessError) as e:
            self._ep_set_flash('bad', e.args[0] if e.args else request.env._("The document could not be updated."))
        else:
            self._ep_set_flash('ok', request.env._("Verified: %s.", what) if decision == 'verify'
                               else request.env._("Sent back: %s.", what))
        return request.redirect('/my/hr/dashboard')
