import pytz
from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.tools import html2plaintext
from odoo.tools.misc import format_amount

from odoo.addons.hr_employee_portal.controllers.main import DEFAULT_TZ, EmployeePortal, _initials, _num
from odoo.addons.hr_employee_portal.models.hr_employee import ATTACHMENT_MAX_COUNT, ATTACHMENT_MAX_SIZE
from odoo.addons.hr_employee_portal_requests.models.approval_request import OPEN_REQUEST_STATES

REQUEST_KINDS = {'new': 'wait', 'pending': 'wait', 'approved': 'ok', 'refused': 'bad', 'cancel': 'bad'}


class EmployeePortalRequests(EmployeePortal):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ep_request_date(self, value, pattern='d MMM y'):
        """A request date (stored in UTC) as the user's day."""
        if not value:
            return ''
        tz = pytz.timezone(request.env.user.tz or DEFAULT_TZ)
        return self._ep_fmt_date(pytz.utc.localize(value).astimezone(tz).date(), pattern)

    def _ep_request_tiles(self, employee):
        """Each portal approval type, after leave and loans."""
        tiles = super()._ep_request_tiles(employee)
        for index, category in enumerate(employee._ep_request_categories()):
            tiles.append({'href': '/my/employee/requests/new/%s' % category.id, 'label': category.name,
                          'icon': 'receipt' if category.has_amount != 'no' else 'letter',
                          'sub': category.description or '', 'sequence': 30 + index})
        return tiles

    def _ep_request_details(self, approval):
        """Date, period, amount... of a request, as one line."""
        parts = []
        if approval.date:
            parts.append(self._ep_request_date(approval.date))
        if approval.date_start and approval.date_end:
            parts.append(request.env._("%(start)s to %(end)s", start=self._ep_request_date(approval.date_start, 'd MMM'),
                                       end=self._ep_request_date(approval.date_end)))
        if approval.amount:
            parts.append(format_amount(request.env, approval.amount, approval.company_id.currency_id))
        if approval.quantity:
            parts.append(request.env._("Quantity %s", _num(approval.quantity)))
        parts += [value for value in (approval.reference, approval.location) if value]
        return ' · '.join(parts)

    def _ep_request_title(self, approval):
        if approval.name and approval.name != approval.category_id.name:
            return '%s: %s' % (approval.category_id.name, approval.name)
        return approval.category_id.name

    def _ep_request_rows(self, employee, limit=None):
        rows = []
        for approval in employee._ep_approval_requests(limit=limit):
            details = self._ep_request_details(approval)
            rows.append({
                'id': approval.id,
                'title': self._ep_request_title(approval),
                'sent': request.env._("Sent %s", self._ep_fmt_date(approval.create_date.date(), 'd MMM y')),
                'sub': ' · '.join(filter(None, [
                    request.env._("Sent %s", self._ep_fmt_date(approval.create_date.date(), 'd MMM y')), details])),
                'note': approval.ep_hr_note,
                'files': [{'id': a.id, 'name': a.name} for a in approval._ep_reply_attachments()],
                'state_label': self._ep_format(approval, 'request_status'),
                'kind': REQUEST_KINDS.get(approval.request_status, 'wait'),
                'can_cancel': approval.request_status in OPEN_REQUEST_STATES,
            })
        return rows

    def _ep_requests_to_review(self):
        approvals = request.env['approval.request'].sudo().search([
            ('request_status', '=', 'pending'),
            ('ep_employee_id', '!=', False),
            ('company_id', 'in', self._ep_allowed_companies().ids),
        ], order='date_confirmed, id')
        return [{
            'id': approval.id,
            'employee': approval.ep_employee_id,
            'initials': _initials(approval.ep_employee_id.name),
            'title': self._ep_request_title(approval),
            'sub': ' · '.join(filter(None, [
                request.env._("Sent %s", self._ep_fmt_date(approval.create_date.date(), 'd MMM')),
                self._ep_request_details(approval)])),
            'reason': html2plaintext(approval.reason or '').strip(),
            'files': [{'id': a.id, 'name': a.name} for a in approval._ep_own_attachments()],
            'can_decide': approval.request_owner_id != request.env.user,
        } for approval in approvals]

    def _ep_request_files(self):
        return [(f.filename, f.read()) for f in request.httprequest.files.getlist('attachments')]

    # ------------------------------------------------------------------
    # Employee pages
    # ------------------------------------------------------------------

    def _ep_profile_values(self, employee, **extra):
        values = super()._ep_profile_values(employee, **extra)
        rows = self._ep_request_rows(employee, limit=5)
        waiting = len([r for r in rows if r['can_cancel']])
        if waiting:
            summary = self._ep_summary(request.env._("%s waiting for HR", waiting), 'wait')
        elif rows:
            summary = self._ep_summary(request.env._("Latest: %(title)s, %(state)s",
                                                     title=rows[0]['title'], state=rows[0]['state_label'].lower()))
        else:
            summary = self._ep_summary(request.env._("No requests yet"))
        values['request_rows'] = rows
        values['summaries']['requests'] = summary
        return values

    @http.route('/my/employee/requests', type='http', auth='user', website=True)
    def ep_requests(self, **kw):
        employee = self._ep_current_employee()
        if not employee:
            return request.redirect('/my/employee')
        return self._ep_render('hr_employee_portal_requests.ep_requests', {
            'page_name': 'ep_requests',
            'employee': employee,
            'request_tiles': self._ep_request_choices(employee),
            'request_rows': self._ep_request_rows(employee, limit=50),
            'flash': self._ep_pop_flash(),
        })

    @http.route('/my/employee/requests/new/<int:category_id>', type='http', auth='user', website=True)
    def ep_request_form(self, category_id, **kw):
        employee = self._ep_current_employee()
        if not employee:
            return request.redirect('/my/employee')
        category = request.env['approval.category'].sudo().browse(category_id).exists()
        if category not in employee._ep_request_categories():
            raise NotFound()
        return self._ep_render('hr_employee_portal_requests.ep_request_form', {
            'page_name': 'ep_requests',
            'employee': employee,
            'category': category,
            'currency_symbol': employee.company_id.currency_id.symbol,
            'flash': self._ep_pop_flash(),
            'attachment_max_count': ATTACHMENT_MAX_COUNT,
            'attachment_max_mb': ATTACHMENT_MAX_SIZE // (1024 * 1024),
        })

    @http.route('/my/employee/requests/new/<int:category_id>/submit', type='http', auth='user',
                methods=['POST'], website=True)
    def ep_request_submit(self, category_id, **post):
        employee = self._ep_current_employee()
        if not employee or not employee.active:
            return request.redirect('/my/employee')
        category = request.env['approval.category'].sudo().browse(category_id).exists()
        if category not in employee._ep_request_categories():
            raise NotFound()
        form_url = '/my/employee/requests/new/%s' % category.id
        try:
            values = {key: (post.get(key) or '').strip() for key in ('subject', 'reason', 'reference', 'location')}
            for key in ('date', 'date_start', 'date_end'):
                values[key] = fields.Date.to_date(post.get(key) or None)
            for key in ('amount', 'quantity'):
                values[key] = float(post.get(key) or 0)
        except ValueError:
            self._ep_set_flash('bad', request.env._("Check the dates and numbers."))
            return request.redirect(form_url)
        try:
            with request.env.cr.savepoint():
                approval = employee._ep_create_approval_request(category, values, self._ep_request_files())
        except (UserError, ValidationError, AccessError) as e:
            self._ep_set_flash('bad', e.args[0] if e.args else request.env._("The request could not be saved."))
            return request.redirect(form_url)
        self._ep_set_flash('ok', request.env._(
            "Request sent: %s. HR will review it; you'll see the answer here.", self._ep_request_title(approval)))
        return request.redirect('/my/employee/requests')

    @http.route('/my/employee/requests/<int:approval_id>/cancel', type='http', auth='user',
                methods=['POST'], website=True)
    def ep_request_cancel(self, approval_id, **kw):
        employee = self._ep_current_employee()
        approval = request.env['approval.request'].sudo().browse(approval_id).exists()
        if not employee or not approval or approval.ep_employee_id != employee:
            raise NotFound()
        try:
            with request.env.cr.savepoint():
                employee._ep_cancel_approval_request(approval)
        except (UserError, ValidationError) as e:
            self._ep_set_flash('bad', e.args[0])
        else:
            self._ep_set_flash('ok', request.env._("Your request was cancelled."))
        return request.redirect('/my/employee/requests')

    @http.route('/my/employee/requests/file/<int:attachment_id>', type='http', auth='user')
    def ep_request_file(self, attachment_id, **kw):
        """A document of a request: for its employee, or for an HR admin."""
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id).exists()
        if not attachment or attachment.res_model != 'approval.request' or attachment.res_field:
            raise NotFound()
        approval = request.env['approval.request'].sudo().browse(attachment.res_id).exists()
        employee = self._ep_current_employee()
        allowed = approval and (
            (employee and approval.ep_employee_id == employee)
            or (self._ep_is_admin() and approval.company_id in self._ep_allowed_companies()))
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
            response.qcontext['request_reviews'] = self._ep_requests_to_review()
        return response

    @http.route('/my/hr/request/<int:approval_id>/<string:decision>', type='http', auth='user',
                methods=['POST'], website=True)
    def ep_admin_request_decision(self, approval_id, decision, note=None, **kw):
        """Approve or refuse a request from the HR dashboard, with a note and documents for the employee."""
        self._ep_require_admin()
        approval = request.env['approval.request'].sudo().browse(approval_id).exists()
        if decision not in ('approve', 'refuse') or not approval or not approval.ep_employee_id \
                or approval.company_id not in self._ep_allowed_companies():
            raise NotFound()
        what = '%s, %s' % (approval.ep_employee_id.name, self._ep_request_title(approval))
        try:
            with request.env.cr.savepoint():
                attachment_values = approval.ep_employee_id._ep_prepare_attachments(self._ep_request_files())
                approval._ep_portal_decide(decision, request.env.user, note, attachment_values)
        except (UserError, ValidationError, AccessError) as e:
            self._ep_set_flash('bad', e.args[0] if e.args else request.env._("The request could not be updated."))
        else:
            self._ep_set_flash('ok', request.env._("Approved: %s.", what) if decision == 'approve'
                               else request.env._("Refused: %s.", what))
        return request.redirect('/my/hr/dashboard')
