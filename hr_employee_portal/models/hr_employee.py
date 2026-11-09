import base64
from datetime import date

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools.mimetypes import guess_mimetype

# Requests still waiting for a first or second approval.
OPEN_LEAVE_STATES = ('confirm', 'validate1')
PAYSLIP_STATES = ('validated', 'paid')

ATTACHMENT_MAX_COUNT = 5
ATTACHMENT_MAX_SIZE = 10 * 1024 * 1024
ATTACHMENT_MIMETYPES = ('application/pdf', 'image/jpeg', 'image/png')

# Half-day requests: the morning or the afternoon of one day.
HALF_DAY_PARTS = ('am', 'pm')


class HrEmployee(models.Model):
    """Employee portal helpers.

    Portal users have no access rights on HR models, so the portal controller
    calls these on its sudo()-ed employee record. Every method only reads or
    changes data of that employee.
    """
    _inherit = 'hr.employee'

    def _ep_portal_leave_types(self):
        """Leave types this employee may request from the portal."""
        self.ensure_one()
        leave_types = self.env['hr.leave.type'].search([
            ('ep_portal_available', '=', True),
            ('leave_validation_type', '!=', 'no_validation'),
            ('company_id', 'in', [False, self.company_id.id]),
        ])
        # A type that needs an allocation can only be requested with one.
        allocated_ids = {
            type_id for _name, data, _requires, type_id in leave_types.get_allocation_data(self)[self]
            if data['max_leaves'] > 0
        }
        return leave_types.filtered(lambda t: not t.requires_allocation or t.id in allocated_ids)

    def _ep_leave_balances(self):
        """Balance per leave type the employee has an allocation for, as computed
        by Odoo's Time Off dashboard (accruals, expired allocations included).
        `remaining` already deducts the requests awaiting approval.

        Odoo deducts upcoming leave from an accrual allocation only once its
        date has come, so it is read on the last day of this year's booked
        leave instead, without the days the accrual will add until then."""
        self.ensure_one()
        LeaveType = self.env['hr.leave.type']
        leave_types = LeaveType.search([('company_id', 'in', [False, self.company_id.id])])
        today = fields.Date.today()
        booked = self.env['hr.leave'].search([
            ('employee_id', '=', self.id),
            ('holiday_status_id', 'in', leave_types.filtered('requires_allocation').ids),
            ('state', 'in', OPEN_LEAVE_STATES + ('validate',)),
            ('request_date_from', '>', today),
            ('request_date_from', '<=', date(today.year, 12, 31)),
        ])
        target = max(booked.mapped('request_date_to'), default=today)
        target = min(target, date(today.year, 12, 31))
        current = leave_types.get_allocation_data(self)[self]
        upcoming = {entry[3]: entry[1] for entry in leave_types.get_allocation_data(self, target)[self]}
        balances = []
        for name, data, _requires, type_id in current:
            if not data['max_leaves']:
                continue
            ahead = upcoming.get(type_id)
            if ahead and ahead['max_leaves']:
                bonus = ahead['accrual_bonus']
                data = dict(ahead, max_leaves=ahead['max_leaves'] - bonus,
                            virtual_remaining_leaves=ahead['virtual_remaining_leaves'] - bonus)
            balances.append({
                'type': LeaveType.browse(type_id),
                'name': name,
                'allocated': data['max_leaves'],
                'taken': data['leaves_approved'],
                'pending': data['leaves_requested'],
                'remaining': data['virtual_remaining_leaves'],
                'unit': 'hour' if data['request_unit'] == 'hour' else 'day',
            })
        return balances

    def _ep_prepare_attachments(self, files):
        """Check uploaded files, given as [(filename, content bytes)], and
        return ir.attachment values. Only PDF and images, by actual content."""
        files = [(name, data) for name, data in files if data]
        if len(files) > ATTACHMENT_MAX_COUNT:
            raise UserError(self.env._("You can attach up to %s files.", ATTACHMENT_MAX_COUNT))
        values = []
        for name, data in files:
            if len(data) > ATTACHMENT_MAX_SIZE:
                raise UserError(self.env._(
                    "%(file)s is too large: files can be up to %(size)s MB.",
                    file=name, size=ATTACHMENT_MAX_SIZE // (1024 * 1024)))
            mimetype = guess_mimetype(data)
            if mimetype not in ATTACHMENT_MIMETYPES:
                raise UserError(self.env._("%s is not a PDF, JPG or PNG file.", name))
            values.append({'name': name or 'document', 'raw': data, 'mimetype': mimetype})
        return values

    def _ep_create_leave_request(self, leave_type, date_from, date_to, description='', files=(), day_part=None):
        """Create a time off request for this employee. `day_part` 'am' or 'pm'
        asks for half of `date_from` only, for types taken in half days.
        Raises UserError or ValidationError with a message for the employee."""
        self.ensure_one()
        if leave_type not in self._ep_portal_leave_types():
            raise UserError(self.env._("This type of time off cannot be requested from the portal."))
        half_day = day_part in HALF_DAY_PARTS
        if half_day:
            if leave_type.request_unit != 'half_day':
                raise UserError(self.env._("%s can only be taken in full days.", leave_type.name))
            date_to = date_from
        if date_to < date_from:
            raise UserError(self.env._("The last day must be on or after the first day."))
        attachment_values = self._ep_prepare_attachments(files)
        values = {
            'employee_id': self.id,
            'holiday_status_id': leave_type.id,
            'request_date_from': date_from,
            'request_date_to': date_to,
            'name': (description or '').strip(),
        }
        if half_day:
            values.update(request_date_from_period=day_part, request_date_to_period=day_part)
        leave = self.env['hr.leave'].create(values)
        if attachment_values:
            self.env['ir.attachment'].create([
                dict(vals, res_model='hr.leave', res_id=leave.id) for vals in attachment_values
            ])
        return leave

    def _ep_cancel_leave_request(self, leave):
        """Cancel one of this employee's requests that is still awaiting approval."""
        self.ensure_one()
        if leave.employee_id != self or leave.state not in OPEN_LEAVE_STATES:
            raise UserError(self.env._("This request can no longer be cancelled."))
        leave._force_cancel(self.env._("Cancelled by the employee from the employee portal."), 'mail.mt_note')

    def _ep_has_photo(self):
        """True when the employee has a real photo, not the letter image Odoo
        generates for employees without one (an SVG)."""
        self.ensure_one()
        image = self.sudo().image_128
        return bool(image) and guess_mimetype(base64.b64decode(image)) != 'image/svg+xml'

    def _ep_payslips(self, limit=None):
        """Validated and paid payslips. Empty when Payroll is not installed."""
        self.ensure_one()
        if 'hr.payslip' not in self.env:
            return self.env['hr.employee']
        return self.env['hr.payslip'].search([
            ('employee_id', '=', self.id),
            ('state', 'in', PAYSLIP_STATES),
        ], order='date_from desc', limit=limit)

    def _ep_join_date(self):
        """Start of the current continuous employment: the first contract of
        the latest run of versions, so a renewal does not reset it."""
        self.ensure_one()
        return self._get_first_contract_date() or self._get_first_version_date() or self.create_date.date()
