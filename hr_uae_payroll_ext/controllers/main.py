from datetime import date

from dateutil.relativedelta import relativedelta
from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import content_disposition, request
from odoo.tools.misc import format_amount
from odoo.tools.translate import LazyTranslate

from odoo.addons.hr_employee_portal.controllers.main import EmployeePortal, _num
from odoo.addons.hr_uae_payroll_ext.models.hr_employee_portal import SETTLEMENT_REPORT_STATES

_lt = LazyTranslate(__name__)

SETTLEMENT_REPORT = 'hr_uae_payroll_ext.action_report_final_settlement'

# Salary lines of the contract shown on the profile, in this order
SALARY_FIELDS = [
    ('wage', _lt("Basic salary")),
    ('l10n_ae_housing_allowance', _lt("Housing allowance")),
    ('l10n_ae_transportation_allowance', _lt("Transport allowance")),
    ('l10n_ae_other_allowances', _lt("Other allowances")),
]
LOAN_KINDS = {'to_approve': 'wait', 'running': 'ok', 'closed': 'ok', 'refused': 'bad'}
ADJUSTMENT_KINDS = {'to_approve': 'wait', 'approved': 'ok', 'paid': 'ok'}
EOS_KINDS = {'draft': 'wait', 'to_approve': 'wait', 'approved': 'wait', 'settlement': 'wait', 'done': 'ok'}
# Attendance calendar: the label of each kind of day (hr.employee._ep_attendance)
DAY_LABELS = [
    ('present', _lt("Present")), ('leave', _lt("Leave")), ('half', _lt("Half-day leave")),
    ('unpaid', _lt("Unpaid leave")), ('holiday', _lt("Public holiday")), ('off', _lt("Day off")),
    ('future', _lt("Coming up")), ('out', _lt("Not under contract")),
]


class EmployeePortalUae(EmployeePortal):

    def _ep_current_employee(self):
        employee = super()._ep_current_employee()
        if employee:
            return employee
        # After the end of service the employee is archived; they keep their
        # portal to see their payslips and final settlement.
        return request.env['hr.employee'].sudo().with_context(active_test=False).search(
            [('user_id', '=', request.env.uid), ('active', '=', False)], order='departure_date desc', limit=1)

    def _ep_selection_label(self, record, fname):
        return dict(record._fields[fname]._description_selection(request.env)).get(record[fname], record[fname])

    # ------------------------------------------------------------------
    # Profile: salary, loans and attendance sections
    # ------------------------------------------------------------------

    def _ep_request_tiles(self, employee):
        tiles = super()._ep_request_tiles(employee)
        tiles.append({'href': '/my/employee/pay#ep-loan-request', 'label': request.env._("Loan or salary advance"),
                      'icon': 'wallet', 'sub': request.env._("Paid back from your salary"), 'sequence': 20})
        return tiles

    def _ep_profile_values(self, employee, **extra):
        values = super()._ep_profile_values(employee, **extra)
        currency = employee.company_id.currency_id

        def fmt(amount):
            return format_amount(request.env, amount, currency)

        version = employee.version_id
        salary_rows = [{'label': str(label), 'value': fmt(version[fname])} for fname, label in SALARY_FIELDS
                       if fname in version._fields and version[fname]]
        if salary_rows and version.l10n_ae_total_salary:
            salary_rows.append({'label': request.env._("Total salary"), 'value': fmt(version.l10n_ae_total_salary)})
        gratuity = employee._uae_gratuity()

        loans = employee._ep_loans()
        running = loans.filtered(lambda l: l.state == 'running')
        waiting = loans.filtered(lambda l: l.state == 'to_approve')
        if running:
            next_lines = running.line_ids.filtered(lambda line: not line.is_recovered).sorted('date')
            loans_summary = self._ep_summary(request.env._(
                "%(left)s left · next %(amount)s", left=fmt(sum(running.mapped('remaining_amount'))),
                amount=fmt(sum(next_lines.filtered(lambda line: line.date == next_lines[:1].date).mapped('amount')))))
        elif waiting:
            loans_summary = self._ep_summary(request.env._("Waiting for approval"), 'wait')
        else:
            loans_summary = self._ep_summary(request.env._("Nothing to pay back"))

        month_start = self._ep_attendance_month(None)
        attendance = self._ep_attendance_values(employee, month_start)
        present = next(s['value'] for s in attendance['stats'] if s['icon'] == 'check')

        values.update({
            'salary_rows': salary_rows,
            'gratuity_amount': fmt(gratuity['amount']) if gratuity['eligible'] else False,
            'profile_loan_rows': [r for r in self._ep_loan_rows(employee, fmt) if r['kind'] == 'wait' or r['show_outstanding']],
            'can_request_loan': employee.active,
            'attendance_rows': [{'label': s['label'], 'value': s['value']} for s in attendance['stats']],
        })
        values['summaries'].update({
            'loans': loans_summary,
            'attendance': self._ep_summary(request.env._(
                "%(month)s: %(present)s present so far", month=attendance['month_label'], present=present)),
        })
        if salary_rows and not values['slips']:
            values['summaries']['pay'] = self._ep_summary(
                request.env._("Total salary %s", fmt(version.l10n_ae_total_salary or version.wage)))
        return values

    # ------------------------------------------------------------------
    # My pay: loans, bonuses and deductions, gratuity
    # ------------------------------------------------------------------

    def _ep_loan_rows(self, employee, fmt):
        rows = []
        for loan in employee._ep_loans():
            next_line = loan.line_ids.filtered(lambda line: not line.is_recovered)[:1]
            if loan.state == 'running' and next_line:
                detail = request.env._("Next: %(amount)s in %(month)s",
                                       amount=fmt(next_line.amount), month=self._ep_fmt_date(next_line.date, 'MMMM y'))
            elif loan.installment_count > 1:
                detail = request.env._("%(count)s monthly instalments of %(amount)s",
                                       count=loan.installment_count, amount=fmt(loan.installment_amount))
            else:
                detail = request.env._("Deducted in one go")
            rows.append({
                'id': loan.id,
                'title': '%s, %s' % (self._ep_selection_label(loan, 'loan_type'), fmt(loan.amount)),
                'sub': '%s · %s · %s' % (loan.name, self._ep_fmt_date(loan.date), detail),
                'outstanding': fmt(loan.remaining_amount),
                'show_outstanding': loan.state == 'running',
                'percent': round(100 * loan.paid_amount / loan.amount) if loan.amount else 0,
                'state_label': self._ep_selection_label(loan, 'state'),
                'kind': LOAN_KINDS.get(loan.state, 'wait'),
            })
        return rows

    def _ep_adjustment_rows(self, employee, fmt):
        return [{
            'title': adjustment.type_id.name,
            'sub': '%s · %s' % (self._ep_fmt_date(adjustment.date), adjustment.reason),
            'amount': ('- %s' if adjustment.is_deduction else '+ %s') % fmt(adjustment.amount),
            'is_deduction': adjustment.is_deduction,
            'state_label': self._ep_selection_label(adjustment, 'state'),
            'kind': ADJUSTMENT_KINDS.get(adjustment.state, 'wait'),
        } for adjustment in employee._ep_adjustments(limit=50)]

    def _ep_pay_values(self, employee):
        currency = employee.company_id.currency_id

        def fmt(amount):
            return format_amount(request.env, amount, currency)

        year_start = fields.Date.today().replace(month=1, day=1)
        this_year = employee._ep_adjustments().filtered(lambda a: a.date >= year_start and a.state != 'to_approve')
        loans = employee._ep_loans()
        gratuity = employee._uae_gratuity()
        eos = employee._ep_end_of_service()
        company = employee.company_id
        gross = employee.version_id.l10n_ae_total_salary

        stats = [
            {'label': request.env._("Outstanding loans"), 'icon': 'wallet',
             'value': fmt(sum(loans.filtered(lambda l: l.state == 'running').mapped('remaining_amount'))),
             'note': request.env._("Deducted from your payslips")},
            {'label': request.env._("Bonuses this year"), 'icon': 'gift',
             'value': fmt(sum(this_year.filtered(lambda a: not a.is_deduction).mapped('amount'))),
             'note': request.env._("Approved bonuses and additions")},
            {'label': request.env._("Deductions this year"), 'icon': 'minus',
             'value': fmt(sum(this_year.filtered('is_deduction').mapped('amount'))),
             'note': request.env._("Fines and other deductions")},
            {'label': request.env._("Gratuity estimate"), 'icon': 'award',
             'value': fmt(gratuity['amount']),
             'note': request.env._("If you left today")},
        ]
        eos_values = eos and {
            'id': eos.id,
            'reason': self._ep_selection_label(eos, 'reason'),
            'state_label': self._ep_selection_label(eos, 'state'),
            'kind': EOS_KINDS.get(eos.state, 'wait'),
            'notice_date': self._ep_fmt_date(eos.notice_date),
            'last_working_day': self._ep_fmt_date(eos.last_working_day),
            'gratuity': fmt(eos.gratuity_amount),
            'net': fmt(eos.payslip_id.net_wage) if eos.payslip_id.state in ('validated', 'paid') else False,
            'can_download': eos.state in SETTLEMENT_REPORT_STATES,
        }
        return {
            'stats': stats,
            'loan_rows': self._ep_loan_rows(employee, fmt),
            'adjustment_rows': self._ep_adjustment_rows(employee, fmt),
            'gratuity': {
                'eligible': gratuity['eligible'],
                'amount': fmt(gratuity['amount']),
                'years': _num(round(gratuity['years'], 2)),
                'basic': fmt(gratuity['basic']),
                'start': self._ep_fmt_date(gratuity['start_date']),
                'unpaid_days': _num(gratuity['unpaid_days']),
                'capped': gratuity['capped'],
            },
            'eos': eos_values,
            'loan_max_months': company.uae_loan_max_installments,
            'loan_max_amount': fmt(gross * company.uae_loan_max_salary_months)
                               if company.uae_loan_max_salary_months and gross else False,
            'currency_symbol': currency.symbol,
            'can_request': employee.active,
        }

    @http.route('/my/employee/pay', type='http', auth='user', website=True)
    def ep_pay(self, **kw):
        employee = self._ep_current_employee()
        if not employee:
            return request.redirect('/my/employee')
        values = self._ep_pay_values(employee)
        values.update({'page_name': 'ep_pay', 'employee': employee, 'flash': self._ep_pop_flash()})
        return self._ep_render('hr_uae_payroll_ext.ep_pay', values)

    @http.route('/my/employee/pay/loan', type='http', auth='user', methods=['POST'], website=True)
    def ep_loan_request(self, loan_type=None, amount=None, installment_count=None, reason=None, **kw):
        employee = self._ep_current_employee()
        if not employee or not employee.active:
            return request.redirect('/my/employee')
        try:
            amount = float(amount or 0)
            installment_count = int(installment_count or 1)
        except ValueError:
            amount = installment_count = 0
        try:
            with request.env.cr.savepoint():
                loan = employee._ep_create_loan_request(loan_type, amount, installment_count, reason)
        except (UserError, ValidationError, AccessError) as e:
            self._ep_set_flash('bad', e.args[0] if e.args else request.env._("The request could not be saved."))
        else:
            self._ep_set_flash('ok', request.env._(
                "Request %(name)s sent. HR will review it; you'll see the status here.", name=loan.name))
        return request.redirect('/my/employee/pay')

    @http.route('/my/employee/end-of-service/<int:eos_id>/pdf', type='http', auth='user')
    def ep_settlement_pdf(self, eos_id, **kw):
        employee = self._ep_current_employee()
        eos = request.env['hr.end.of.service'].sudo().browse(eos_id).exists()
        if not employee or not eos or eos.employee_id != employee or eos.state not in SETTLEMENT_REPORT_STATES:
            raise NotFound()
        pdf = request.env['ir.actions.report'].sudo()._render_qweb_pdf(SETTLEMENT_REPORT, [eos.id])[0]
        filename = '%s.pdf' % (eos.name or 'final-settlement').replace('/', '-')
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', content_disposition(filename)),
        ])

    # ------------------------------------------------------------------
    # Attendance: worked out from the work schedule and leave
    # ------------------------------------------------------------------

    def _ep_attendance_month(self, month):
        """First day of the month asked for as YYYY-MM, this month otherwise."""
        today = fields.Date.context_today(request.env.user)
        try:
            return date(*map(int, (month or '').split('-')), 1) if month else today.replace(day=1)
        except (TypeError, ValueError):
            return today.replace(day=1)

    def _ep_attendance_values(self, employee, month_start):
        data = employee._ep_attendance(month_start)
        totals = data['totals']
        today = fields.Date.context_today(request.env.user)
        month_label = self._ep_fmt_date(month_start, 'MMMM y')

        def days(value):
            value = _num(value)
            return request.env._("%s day", value) if value == '1' else request.env._("%s days", value)

        stats = [
            {'label': request.env._("Working days"), 'icon': 'leave', 'value': days(totals['working']),
             'note': request.env._("In your schedule, %s", month_label)},
            {'label': request.env._("Present"), 'icon': 'check', 'value': days(totals['present']),
             'note': request.env._("Up to today") if month_start <= today <= month_start + relativedelta(months=1, days=-1)
                     else request.env._("Working days not on leave")},
            {'label': request.env._("On leave"), 'icon': 'sun', 'value': days(totals['leave'] + totals['unpaid']),
             'note': request.env._("of which %s unpaid", days(totals['unpaid'])) if totals['unpaid']
                     else request.env._("Approved leave")},
            {'label': request.env._("Public holidays"), 'icon': 'sparkle', 'value': days(totals['holiday']),
             'note': request.env._("On working days")},
        ]
        # Weeks from Monday; days outside the month are empty cells.
        cells = [None] * month_start.weekday() + [dict(d, number=d['date'].day, is_today=d['date'] == today)
                                                 for d in data['days']]
        cells += [None] * (-len(cells) % 7)
        return {
            'stats': stats,
            'weeks': [cells[i:i + 7] for i in range(0, len(cells), 7)],
            'weekdays': [self._ep_fmt_date(month_start + relativedelta(weekday=i), 'EEE') for i in range(7)],
            'month_label': month_label,
            'prev_month': (month_start - relativedelta(months=1)).strftime('%Y-%m'),
            'next_month': (month_start + relativedelta(months=1)).strftime('%Y-%m'),
            'leave_rows': [{
                'type': leave.holiday_status_id.name,
                'dates': self._ep_leave_label(leave),
                'in_month': days(total),
                'unpaid': leave.holiday_status_id.uae_pay_rate == '0',
            } for leave, total in data['leaves']],
            'day_labels': dict(DAY_LABELS),
        }

    @http.route('/my/employee/attendance', type='http', auth='user', website=True)
    def ep_attendance(self, month=None, **kw):
        employee = self._ep_current_employee()
        if not employee:
            return request.redirect('/my/employee')
        values = self._ep_attendance_values(employee, self._ep_attendance_month(month))
        values.update({'page_name': 'ep_attendance', 'employee': employee})
        return self._ep_render('hr_uae_payroll_ext.ep_attendance', values)

    @http.route('/my/employee/timesheets', type='http', auth='user', website=True)
    def ep_timesheets(self, **kw):
        """Old address: hours are not logged, attendance comes from leave."""
        return request.redirect('/my/employee/attendance')
