from collections import Counter
from datetime import datetime, timedelta

import pytz
from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import content_disposition, request
from odoo.tools.image import image_data_uri
from odoo.tools.misc import format_amount, format_date
from odoo.tools.translate import LazyTranslate

from odoo.addons.hr_employee_portal.models.hr_employee import (
    ATTACHMENT_MAX_COUNT, ATTACHMENT_MAX_SIZE, HALF_DAY_PARTS, OPEN_LEAVE_STATES, PAYSLIP_STATES,
)
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.web.controllers.home import Home

_lt = LazyTranslate(__name__)

# Profile fields of the folding sections (key, fields). Fields missing in your
# Odoo version, and empty ones, are skipped.
PROFILE_SECTIONS = [
    ('job', [
        ('job_title', _lt("Job title")),
        ('department_id', _lt("Department")),
        ('parent_id', _lt("Manager")),
        ('work_location_id', _lt("Work location")),
        ('work_email', _lt("Work email")),
        ('mobile_phone', _lt("Work mobile")),
        ('contract_type_id', _lt("Contract type")),
        ('contract_date_start', _lt("Contract start")),
        ('contract_date_end', _lt("Contract end")),
        ('resource_calendar_id', _lt("Working hours")),
    ]),
    ('personal', [
        ('private_phone', _lt("Personal phone")),
        ('private_email', _lt("Personal email")),
        ('birthday', _lt("Date of birth")),
        ('country_id', _lt("Nationality")),
        ('marital', _lt("Marital status")),
    ]),
    ('documents', [
        ('passport_id', _lt("Passport number")),
        ('visa_no', _lt("Visa number")),
        ('permit_no', _lt("Work permit number")),
        ('identification_id', _lt("ID number")),
    ]),
]

# Shown under the title of the Personal section
PERSONAL_SUMMARY_FIELDS = ('private_phone', 'private_email', 'country_id')

# Expiry dates tracked for alerts: (label, candidate fields).
# The first field that exists and has a value is used, so a Studio field wins over
# Odoo's standard field and the same document never appears twice.
DOCUMENT_FIELDS = [
    (_lt("Emirates ID"), ['x_studio_id_expiration_date']),
    (_lt("Visa"), ['visa_expire']),
    (_lt("Work permit"), ['x_studio_work_permit_expiration_date', 'work_permit_expiration_date']),
    (_lt("Passport"), ['x_studio_passport_expiration_date', 'passport_expiration_date']),
    (_lt("Health insurance"), ['x_studio_health_insurance_expiration_date']),
]

EXPIRY_WINDOW_DAYS = 30
# The leave page draws one block per day; above this many days the blocks are scaled.
MAX_DAY_BLOCKS = 60
PAYSLIP_REPORT = 'hr_payroll.action_report_payslip'
DEFAULT_TZ = 'Asia/Dubai'
# Bars on the red headcount card: the yellows, white and pinks of the website.
DEPARTMENT_COLORS = ['#F5A524', '#FFFFFF', '#F4C430', '#F3DCDC', '#FFD98A', '#E8A0A2']
EMPLOYEE_PATHS = ('/my/employee', '/my/hr')
FLASH_KEY = 'ep_flash'


def _num(value):
    """12.0 -> '12', 1.5 -> '1.5'."""
    return ('%.2f' % (value or 0.0)).rstrip('0').rstrip('.')


def _days(value):
    value = _num(value)
    return request.env._("%s day", value) if value == '1' else request.env._("%s days", value)


def _hours(value):
    value = _num(value)
    return request.env._("%s hour", value) if value == '1' else request.env._("%s hours", value)


def _day_blocks(taken, pending, remaining):
    """One entry per day ('taken', 'pending' or 'free') for the 3D day blocks,
    and whether the blocks had to be scaled down to MAX_DAY_BLOCKS."""
    counts = [max(round(value), 0) for value in (taken, pending, remaining)]
    total = sum(counts)
    scaled = total > MAX_DAY_BLOCKS
    if scaled:
        counts = [round(count * MAX_DAY_BLOCKS / total) for count in counts]
    return ['taken'] * counts[0] + ['pending'] * counts[1] + ['free'] * counts[2], scaled


def _initials(name):
    parts = [p for p in (name or '').split() if p]
    return ''.join(p[0] for p in parts[:2]).upper() or '?'


def _status_kind(state):
    if state == 'validate':
        return 'ok'
    if state in OPEN_LEAVE_STATES:
        return 'wait'
    return 'bad'


class EmployeeLogin(Home):

    def _ep_is_employee_login(self, redirect):
        """True when this login belongs to the employee portal, not the shop."""
        return bool(request.params.get('ep_portal')) or (redirect or '').startswith(EMPLOYEE_PATHS)

    @http.route()
    def web_login(self, redirect=None, **kw):
        response = super().web_login(redirect=redirect, **kw)
        # Only employee logins get the branded page; shop customers keep the website login.
        if (getattr(response, 'template', None) == 'web.login'
                and not request.session.debug
                and self._ep_is_employee_login(redirect)):
            response.template = 'hr_employee_portal.ep_login'
        return response

    @http.route('/employee/login', type='http', auth='public', website=True, sitemap=False)
    def ep_login_page(self, **kw):
        """Short, shareable address for employees."""
        if not request.env.user._is_public():
            return request.redirect('/my/employee')
        return request.redirect('/web/login?redirect=/my/employee')

    def _login_redirect(self, uid, redirect=None):
        # Portal users linked to an employee land on their portal unless a page was requested.
        if not redirect:
            user = request.env['res.users'].sudo().browse(uid)
            employee = request.env['hr.employee'].sudo().search([('user_id', '=', uid)], limit=1)
            if employee and user._is_portal():
                return '/my/employee'
        return super()._login_redirect(uid, redirect=redirect)


class EmployeePortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ep_current_employee(self):
        """The employee of the logged-in user, in the current company if the
        user is linked to employees in several companies. Returned in sudo:
        portal users have no access rights on HR models."""
        employees = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.uid)])
        return employees.filtered(lambda e: e.company_id == request.env.company)[:1] or employees[:1]

    def _ep_is_admin(self):
        user = request.env.user
        return (user.has_group('hr.group_hr_manager')
                or user.has_group('hr_employee_portal.group_portal_hr_admin'))

    def _ep_require_admin(self):
        if not self._ep_is_admin():
            raise NotFound()

    def _ep_allowed_companies(self):
        return request.env.user.company_ids

    def _ep_now(self):
        tz = pytz.timezone(request.env.user.tz or DEFAULT_TZ)
        return datetime.now(pytz.utc).astimezone(tz)

    def _ep_fmt_date(self, value, pattern=None):
        if not value:
            return ''
        return format_date(request.env, value, date_format=pattern) if pattern else format_date(request.env, value)

    def _ep_set_flash(self, kind, message):
        """Message shown once on the next page. Kept in the session, not the
        URL, so nobody can make a link that displays their own text."""
        request.session[FLASH_KEY] = {'kind': kind, 'message': message}

    def _ep_pop_flash(self):
        return request.session.pop(FLASH_KEY, None)

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        employee = self._ep_current_employee()
        name = employee.name if employee else request.env.user.name
        now = self._ep_now()
        if now.hour < 12:
            greeting = request.env._("Good morning")
        elif now.hour < 17:
            greeting = request.env._("Good afternoon")
        else:
            greeting = request.env._("Good evening")
        values.update({
            'ep_employee': employee,
            'ep_is_admin': self._ep_is_admin(),
            'ep_user_name': name,
            'ep_user_initials': _initials(name),
            'ep_greeting': greeting,
            'ep_first_name': (name or '').split()[0] if name else '',
            'ep_today_label': self._ep_fmt_date(now.date(), 'EEEE, d MMMM y'),
        })
        return values

    def _ep_render(self, template, values):
        render_values = self._prepare_portal_layout_values()
        render_values['image_data_uri'] = image_data_uri
        render_values.update(values)
        return request.render(template, render_values)

    def _ep_format(self, record, fname):
        field = record._fields[fname]
        value = record[fname]
        if not value:
            return False
        if field.type == 'many2one':
            return value.display_name
        if field.type == 'selection':
            return dict(field._description_selection(request.env)).get(value, value)
        if field.type == 'date':
            return self._ep_fmt_date(value)
        return value

    def _ep_profile_rows(self, employee):
        """{section key: [{'label', 'value'}]} for the fields of PROFILE_SECTIONS."""
        result = {}
        for key, field_list in PROFILE_SECTIONS:
            rows = []
            for fname, label in field_list:
                if fname in employee._fields:
                    value = self._ep_format(employee, fname)
                    if value:
                        rows.append({'label': str(label), 'value': value})
            result[key] = rows
        return result

    def _ep_document_dates(self, employee):
        """[(label, expiry date)] for each tracked document that has a date."""
        result = []
        for label, candidates in DOCUMENT_FIELDS:
            for fname in candidates:
                if fname in employee._fields and employee[fname]:
                    value = employee[fname]
                    result.append((str(label), value.date() if isinstance(value, datetime) else value))
                    break
        return result

    def _ep_documents(self, employee):
        today = fields.Date.today()
        documents = []
        for label, expiry in self._ep_document_dates(employee):
            days = (expiry - today).days
            status = 'expired' if days < 0 else 'soon' if days <= EXPIRY_WINDOW_DAYS else 'valid'
            documents.append({
                'label': label,
                'date': self._ep_fmt_date(expiry),
                'short_date': self._ep_fmt_date(expiry, 'd MMM y'),
                'days': days,
                'status': status,
            })
        return documents

    def _ep_tenure(self, join_date):
        today = fields.Date.today()
        months = (today.year - join_date.year) * 12 + today.month - join_date.month
        if today.day < join_date.day:
            months -= 1
        years, months = divmod(max(months, 0), 12)
        if years and months:
            return request.env._("%(years)s yr %(months)s mo", years=years, months=months)
        if years:
            return request.env._("1 year") if years == 1 else request.env._("%s years", years)
        return request.env._("1 month") if months == 1 else request.env._("%s months", months)

    def _ep_leave_balances(self, employee):
        """Balances with display values, from Odoo's own leave computation."""
        result = []
        for entry in employee._ep_leave_balances():
            fmt = _hours if entry['unit'] == 'hour' else _days
            meta = request.env._("%s taken", _num(entry['taken']))
            if entry['pending']:
                meta = request.env._("%(taken)s, %(pending)s awaiting approval",
                                     taken=meta, pending=_num(entry['pending']))
            allocated = entry['allocated']
            blocks, blocks_scaled = _day_blocks(entry['taken'], entry['pending'], entry['remaining'])
            entry.update({
                'blocks': blocks if entry['unit'] == 'day' else [],
                'blocks_scaled': blocks_scaled,
                'taken_display': _num(entry['taken']),
                'pending_display': _num(entry['pending']),
                'remaining_display': _num(entry['remaining']),
                'remaining_label': fmt(entry['remaining']),
                'allocated_display': _num(allocated),
                'allocated_label': fmt(allocated),
                'meta': meta,
                'percent': max(0, min(100, round(100 * entry['remaining'] / allocated))) if allocated else 0,
            })
            result.append(entry)
        return result

    def _ep_leave_label(self, leave):
        start, end = leave.request_date_from, leave.request_date_to
        if start == end and leave.request_unit_half and leave.request_date_from_period == leave.request_date_to_period:
            dates = '%s (%s)' % (self._ep_fmt_date(start, 'd MMM'),
                                 self._ep_format(leave, 'request_date_from_period').lower())
        elif start == end:
            dates = self._ep_fmt_date(start, 'd MMM')
        else:
            dates = request.env._("%(start)s to %(end)s",
                                  start=self._ep_fmt_date(start, 'd MMM'),
                                  end=self._ep_fmt_date(end, 'd MMM'))
        return '%s, %s' % (dates, _days(leave.number_of_days))

    def _ep_leave_rows(self, employee, limit=None):
        leaves = request.env['hr.leave'].sudo().search(
            [('employee_id', '=', employee.id)], order='request_date_from desc', limit=limit)
        return [{
            'id': leave.id,
            'type': leave.holiday_status_id.name,
            'dates': self._ep_leave_label(leave),
            'state_label': self._ep_format(leave, 'state'),
            'kind': _status_kind(leave.state),
            'can_cancel': leave.state in OPEN_LEAVE_STATES,
        } for leave in leaves]

    def _ep_next_leave(self, employee):
        return request.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', 'in', OPEN_LEAVE_STATES + ('validate',)),
            ('request_date_to', '>=', fields.Date.today()),
        ], order='request_date_from', limit=1)

    def _ep_has_payroll(self):
        return 'hr.payslip' in request.env.registry

    def _ep_payslip_rows(self, slips):
        rows = []
        for slip in slips:
            currency = slip.currency_id or slip.company_id.currency_id
            rows.append({
                'id': slip.id,
                'month': self._ep_fmt_date(slip.date_from, 'MMMM y'),
                'period': request.env._("%(start)s to %(end)s",
                                        start=self._ep_fmt_date(slip.date_from, 'd MMM'),
                                        end=self._ep_fmt_date(slip.date_to, 'd MMM y')),
                'net': format_amount(request.env, slip.net_wage, currency),
            })
        return rows

    def _ep_profile_values(self, employee, **extra):
        join_date = employee._ep_join_date()
        balances = self._ep_leave_balances(employee)
        pending = request.env['hr.leave'].sudo().search(
            [('employee_id', '=', employee.id), ('state', 'in', OPEN_LEAVE_STATES)],
            order='request_date_from')
        slips = self._ep_payslip_rows(employee._ep_payslips(limit=3))

        stats = []
        if balances:
            main = balances[0]
            stats.append({'label': request.env._("%s left", main['name']), 'value': main['remaining_label'], 'icon': 'leave',
                          'note': request.env._("of %s allocated", main['allocated_display'])})
        stats.append({'label': request.env._("Length of service"), 'value': self._ep_tenure(join_date), 'icon': 'award',
                      'note': request.env._("Joined %s", self._ep_fmt_date(join_date))})
        if len(pending) == 1:
            pending_value = request.env._("1 request")
        else:
            pending_value = request.env._("%s requests", len(pending))
        stats.append({'label': request.env._("Awaiting approval"), 'value': pending_value, 'icon': 'hourglass',
                      'note': ('%s, %s' % (pending[0].holiday_status_id.name, self._ep_leave_label(pending[0]))
                               if pending else request.env._("Nothing pending"))})
        if slips:
            stats.append({'label': request.env._("Last net pay"), 'value': slips[0]['net'], 'note': slips[0]['month'],
                          'icon': 'payslip'})
        else:
            nxt = self._ep_next_leave(employee)
            stats.append({
                'label': request.env._("Next leave"),
                'icon': 'sun',
                'value': self._ep_fmt_date(nxt.request_date_from, 'd MMM') if nxt else request.env._("None booked"),
                'note': nxt.holiday_status_id.name if nxt else request.env._("Plan some time off"),
            })

        number = False
        for fname in ('registration_number', 'barcode'):
            if fname in employee._fields and employee[fname]:
                number = employee[fname]
                break

        rows = self._ep_profile_rows(employee)
        tenure = self._ep_tenure(join_date)
        rows['job'][:0] = [
            {'label': request.env._("Joined"), 'value': self._ep_fmt_date(join_date)},
            {'label': request.env._("Length of service"), 'value': tenure},
        ]
        documents = self._ep_documents(employee)
        next_leave = self._ep_next_leave(employee)
        role_line = ', '.join(filter(None, [employee.job_title or employee.job_id.name, employee.department_id.name]))

        values = {
            'employee': employee,
            'employee_number': number,
            'role_line': role_line,
            'stats': stats,
            'join_date_label': self._ep_fmt_date(join_date),
            'tenure': tenure,
            'profile_rows': rows,
            'documents': documents,
            'balances': balances,
            'pending_leaves': [{
                'type': leave.holiday_status_id.name, 'dates': self._ep_leave_label(leave),
            } for leave in pending],
            'next_leave': next_leave and {
                'type': next_leave.holiday_status_id.name, 'dates': self._ep_leave_label(next_leave),
                'state_label': self._ep_format(next_leave, 'state'), 'kind': _status_kind(next_leave.state),
            },
            'has_payroll': self._ep_has_payroll(),
            'slips': slips,
            'request_tiles': self._ep_request_choices(employee) if employee.active else [],
            'summaries': {
                'personal': self._ep_summary(' · '.join(
                    str(self._ep_format(employee, fname)) for fname in PERSONAL_SUMMARY_FIELDS
                    if fname in employee._fields and employee[fname])
                    or (request.env._("Tap to see your details") if rows['personal'] else request.env._("Nothing on file yet"))),
                'job': self._ep_summary(
                    request.env._("Contract until %s", self._ep_fmt_date(employee.contract_date_end))
                    if 'contract_date_end' in employee._fields and employee.contract_date_end
                    else role_line or request.env._("Joined %s", self._ep_fmt_date(join_date))),
                'documents': self._ep_documents_summary(documents),
                'leave': self._ep_leave_summary(balances, pending),
                'pay': self._ep_summary(
                    request.env._("%(month)s: %(net)s net", month=slips[0]['month'], net=slips[0]['net'])
                    if slips else request.env._("No payslips yet")),
            },
            'admin_view': False,
            'leave_rows': [],
        }
        values.update(extra)
        return values

    def _ep_request_tiles(self, employee):
        """Everything an employee can ask for (New request menu). Other modules add
        their kinds; `sequence` orders them."""
        return [{'href': '/my/employee/leaves', 'label': request.env._("Leave"), 'icon': 'leave',
                 'sub': request.env._("Annual, sick and other leave"), 'sequence': 10}]

    def _ep_request_choices(self, employee):
        return sorted(self._ep_request_tiles(employee), key=lambda tile: tile['sequence'])

    def _ep_summary(self, text, kind=None):
        """The one-line answer under the title of a profile section; kind colours it."""
        return {'text': text, 'kind': kind}

    def _ep_documents_summary(self, documents):
        expired = [d['label'] for d in documents if d['status'] == 'expired']
        if expired:
            return self._ep_summary(request.env._("Expired: %s", ', '.join(expired)), 'bad')
        soon = [d for d in documents if d['status'] == 'soon']
        if soon:
            return self._ep_summary(request.env._("%(doc)s expires in %(days)s days",
                                                  doc=soon[0]['label'], days=soon[0]['days']), 'wait')
        if documents:
            return self._ep_summary(request.env._("All valid"), 'ok')
        return self._ep_summary(request.env._("No documents on file"))

    def _ep_leave_summary(self, balances, pending):
        if balances:
            text = request.env._("%(type)s: %(left)s left", type=balances[0]['name'], left=balances[0]['remaining_label'])
        else:
            text = request.env._("No leave allocated yet")
        if pending:
            text = request.env._("%(text)s · %(count)s waiting for approval", text=text, count=len(pending))
        return self._ep_summary(text, 'wait' if pending else None)

    # ------------------------------------------------------------------
    # Employee pages
    # ------------------------------------------------------------------

    @http.route('/my/employee', type='http', auth='user', website=True)
    def ep_profile(self, **kw):
        employee = self._ep_current_employee()
        if not employee:
            return self._ep_render('hr_employee_portal.ep_no_employee', {'page_name': 'ep_profile'})
        return self._ep_render('hr_employee_portal.ep_profile',
                               self._ep_profile_values(employee, page_name='ep_profile'))

    @http.route('/my/employee/leaves', type='http', auth='user', website=True)
    def ep_leaves(self, **kw):
        employee = self._ep_current_employee()
        if not employee:
            return request.redirect('/my/employee')
        nxt = self._ep_next_leave(employee)
        return self._ep_render('hr_employee_portal.ep_leaves', {
            'page_name': 'ep_leaves',
            'employee': employee,
            'balances': self._ep_leave_balances(employee),
            'leave_rows': self._ep_leave_rows(employee, limit=20),
            'leave_types': employee._ep_portal_leave_types(),
            'next_leave': nxt and {
                'dates': self._ep_leave_label(nxt),
                'day': self._ep_fmt_date(nxt.request_date_from, 'd'),
                'weekday': self._ep_fmt_date(nxt.request_date_from, 'EEEE'),
                'month': self._ep_fmt_date(nxt.request_date_from, 'MMM'),
                'type': nxt.holiday_status_id.name,
                'state': request.env._("approved") if nxt.state == 'validate' else request.env._("awaiting approval"),
            },
            'balance_date': self._ep_fmt_date(fields.Date.today(), 'd MMMM y'),
            'flash': self._ep_pop_flash(),
            'attachment_max_count': ATTACHMENT_MAX_COUNT,
            'attachment_max_mb': ATTACHMENT_MAX_SIZE // (1024 * 1024),
        })

    @http.route('/my/employee/leaves/request', type='http', auth='user', methods=['POST'], website=True)
    def ep_leave_request(self, leave_type_id=None, date_from=None, date_to=None, description=None,
                         day_part=None, **kw):
        employee = self._ep_current_employee()
        if not employee:
            return request.redirect('/my/employee')
        try:
            leave_type = request.env['hr.leave.type'].sudo().browse(int(leave_type_id or 0)).exists()
            start = fields.Date.to_date(date_from)
            # A half day is one day: the form hides the last day.
            end = start if day_part in HALF_DAY_PARTS else fields.Date.to_date(date_to)
        except ValueError:
            leave_type = start = end = None
        if not leave_type or not start or not end:
            self._ep_set_flash('bad', request.env._("Choose a leave type and both dates."))
            return request.redirect('/my/employee/leaves')

        files = [(f.filename, f.read()) for f in request.httprequest.files.getlist('attachments')]
        try:
            with request.env.cr.savepoint():
                leave = employee._ep_create_leave_request(leave_type, start, end, description, files, day_part)
        except (UserError, ValidationError, AccessError) as e:
            self._ep_set_flash('bad', e.args[0] if e.args else request.env._("The request could not be saved."))
        else:
            self._ep_set_flash('ok', request.env._(
                "Request sent: %(type)s, %(dates)s. It is now awaiting approval.",
                type=leave.holiday_status_id.name, dates=self._ep_leave_label(leave)))
        return request.redirect('/my/employee/leaves')

    @http.route('/my/employee/leaves/<int:leave_id>/cancel', type='http', auth='user', methods=['POST'], website=True)
    def ep_leave_cancel(self, leave_id, **kw):
        employee = self._ep_current_employee()
        leave = request.env['hr.leave'].sudo().browse(leave_id).exists()
        if not employee or not leave or leave.employee_id != employee:
            raise NotFound()
        try:
            with request.env.cr.savepoint():
                employee._ep_cancel_leave_request(leave)
        except (UserError, ValidationError) as e:
            self._ep_set_flash('bad', e.args[0])
        else:
            self._ep_set_flash('ok', request.env._("Your request was cancelled."))
        return request.redirect('/my/employee/leaves')

    @http.route('/my/employee/password', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def ep_password(self, **post):
        """Change password inside the employee portal (uses Odoo's own portal logic)."""
        values = {'page_name': 'ep_password', 'errors': {}, 'success': False}
        if request.httprequest.method == 'POST':
            result = self._update_password(post.get('old') or '', post.get('new1') or '', post.get('new2') or '')
            errors = (result.get('errors') or {}).get('password')
            if errors:
                values['errors'] = errors if isinstance(errors, dict) else {'general': errors}
            else:
                values['success'] = True
        return self._ep_render('hr_employee_portal.ep_password', values)

    @http.route('/my/employee/payslips', type='http', auth='user', website=True)
    def ep_payslips(self, **kw):
        employee = self._ep_current_employee()
        if not employee:
            return request.redirect('/my/employee')
        return self._ep_render('hr_employee_portal.ep_payslips', {
            'page_name': 'ep_payslips',
            'employee': employee,
            'has_payroll': self._ep_has_payroll(),
            'slips': self._ep_payslip_rows(employee._ep_payslips()),
        })

    @http.route('/my/employee/payslips/<int:slip_id>/pdf', type='http', auth='user')
    def ep_payslip_pdf(self, slip_id, **kw):
        if not self._ep_has_payroll():
            raise NotFound()
        slip = request.env['hr.payslip'].sudo().browse(slip_id).exists()
        employee = self._ep_current_employee()
        allowed = slip and slip.state in PAYSLIP_STATES and (
            (employee and slip.employee_id == employee)
            or (self._ep_is_admin() and slip.company_id in self._ep_allowed_companies())
        )
        if not allowed:
            raise NotFound()
        try:
            pdf = request.env['ir.actions.report'].sudo()._render_qweb_pdf(slip.struct_id.report_id or PAYSLIP_REPORT, [slip.id])[0]
        except ValueError:
            raise NotFound()
        filename = '%s.pdf' % (slip.name or 'payslip').replace('/', '-')
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', content_disposition(filename)),
        ])

    # ------------------------------------------------------------------
    # Admin pages
    # ------------------------------------------------------------------

    @http.route('/my/hr/leave/<int:leave_id>/<string:decision>', type='http', auth='user', methods=['POST'], website=True)
    def ep_admin_leave_decision(self, leave_id, decision, **kw):
        """Approve or refuse a pending request from the HR dashboard."""
        self._ep_require_admin()
        leave = request.env['hr.leave'].sudo().browse(leave_id).exists()
        if decision not in ('approve', 'refuse') or not leave \
                or leave.employee_id.company_id not in self._ep_allowed_companies():
            raise NotFound()
        what = '%s, %s, %s' % (leave.employee_id.name, leave.holiday_status_id.name, self._ep_leave_label(leave))
        try:
            with request.env.cr.savepoint():
                leave._ep_portal_decide(decision, request.env.user)
        except (UserError, ValidationError, AccessError) as e:
            self._ep_set_flash('bad', e.args[0] if e.args else request.env._("The request could not be updated."))
        else:
            self._ep_set_flash('ok', request.env._("Approved: %s.", what) if decision == 'approve'
                               else request.env._("Refused: %s.", what))
        return request.redirect('/my/hr/dashboard')

    @http.route('/my/hr/dashboard', type='http', auth='user', website=True)
    def ep_admin_dashboard(self, q=None, department=None, **kw):
        self._ep_require_admin()
        Employee = request.env['hr.employee'].sudo()
        Leave = request.env['hr.leave'].sudo()
        today = fields.Date.today()

        employees = Employee.search([('company_id', 'in', self._ep_allowed_companies().ids)], order='name')

        away = Leave.search([
            ('employee_id', 'in', employees.ids), ('state', '=', 'validate'),
            ('request_date_from', '<=', today), ('request_date_to', '>=', today),
        ])
        away_ids = set(away.mapped('employee_id').ids)
        pending = Leave.search([
            ('employee_id', 'in', employees.ids), ('state', 'in', OPEN_LEAVE_STATES),
        ], order='request_date_from')

        expiring = []
        limit_date = today + timedelta(days=EXPIRY_WINDOW_DAYS)
        for emp in employees:
            for label, expiry in self._ep_document_dates(emp):
                if expiry > limit_date:
                    continue
                days = (expiry - today).days
                when = self._ep_fmt_date(expiry, 'd MMM')
                expiring.append({
                    'employee': emp, 'doc': label, 'days': days,
                    'kind': 'bad' if days < 0 else 'wait',
                    'when': request.env._("Expired %s", when) if days < 0 else when,
                })
        expiring.sort(key=lambda d: d['days'])

        counts = Counter(e.department_id.id for e in employees)
        departments = employees.mapped('department_id').sorted('name')
        dept_rows = sorted(
            [{'name': d.name, 'count': counts[d.id]} for d in departments]
            + ([{'name': request.env._("No department"), 'count': counts[False]}] if counts.get(False) else []),
            key=lambda r: -r['count'])
        top_count = max([r['count'] for r in dept_rows] or [1])
        for i, row in enumerate(dept_rows):
            row['color'] = DEPARTMENT_COLORS[i % len(DEPARTMENT_COLORS)]
            row['height'] = round(100 * row['count'] / top_count)

        directory = employees
        if q:
            needle = q.strip().lower()
            directory = directory.filtered(
                lambda e: needle in (e.name or '').lower()
                or needle in (e.job_title or '').lower()
                or needle in (e.work_email or '').lower())
        selected_department = 0
        if department:
            try:
                selected_department = int(department)
            except ValueError:
                selected_department = 0
            if selected_department:
                directory = directory.filtered(lambda e: e.department_id.id == selected_department)

        expired_count = len([d for d in expiring if d['days'] < 0])
        soon_count = len(expiring) - expired_count
        doc_parts = []
        if expired_count:
            doc_parts.append(request.env._("%s expired", expired_count))
        if soon_count:
            doc_parts.append(request.env._("%s due soon", soon_count))
        away_names = away.mapped('employee_id.name')
        if not away_names:
            away_note = request.env._("Everyone is in")
        elif len(away_names) == 1:
            away_note = away_names[0]
        else:
            away_note = request.env._("%(name)s and %(count)s more",
                                      name=away_names[0].split()[0], count=len(away_names) - 1)
        kpi_notes = {
            'away': away_note,
            'approvals': (request.env._("Nothing waiting") if not pending else
                          request.env._("Oldest from %s", self._ep_fmt_date(pending[0].request_date_from, 'd MMM'))),
            'documents': ', '.join(doc_parts) if doc_parts else request.env._("All up to date"),
        }

        return self._ep_render('hr_employee_portal.ep_admin_dashboard', {
            'page_name': 'ep_admin_dashboard',
            'employees': employees,
            'departments': departments,
            'dept_rows': dept_rows,
            'dept_label': ', '.join('%s %s' % (r['name'], r['count']) for r in dept_rows),
            'away': [{'employee': l.employee_id, 'detail': request.env._(
                "%(type)s, back after %(date)s",
                type=l.holiday_status_id.name, date=self._ep_fmt_date(l.request_date_to, 'd MMMM'))} for l in away],
            'approvals': [{
                'employee': l.employee_id,
                'initials': _initials(l.employee_id.name),
                'detail': '%s, %s' % (l.holiday_status_id.name, self._ep_leave_label(l)),
                'id': l.id,
                'can_decide': l.employee_id.user_id != request.env.user,
            } for l in pending],
            'expiring': expiring,
            'kpi_notes': kpi_notes,
            'flash': self._ep_pop_flash(),
            'directory': [{
                'employee': e, 'initials': _initials(e.name),
                'on_leave': e.id in away_ids,
            } for e in directory],
            'selected_department': selected_department,
            'q': q or '',
        })

    @http.route('/my/hr/employee/<int:employee_id>', type='http', auth='user', website=True)
    def ep_admin_employee(self, employee_id, **kw):
        self._ep_require_admin()

        employee = request.env['hr.employee'].sudo().browse(employee_id).exists()
        if not employee or employee.company_id not in self._ep_allowed_companies():
            raise NotFound()
        values = self._ep_profile_values(employee, page_name='ep_admin_dashboard', admin_view=True)
        values['leave_rows'] = self._ep_leave_rows(employee, limit=10)
        return self._ep_render('hr_employee_portal.ep_profile', values)
