from datetime import datetime, time

import pytz

from odoo import models
from odoo.exceptions import UserError
from odoo.tools import plaintext2html

from odoo.addons.hr_employee_portal_requests.models.approval_request import OPEN_REQUEST_STATES

DEFAULT_TZ = 'Asia/Dubai'
# Fields of an approval type the portal form offers: has_* switch -> request field.
SIMPLE_FIELDS = (
    ('has_amount', 'amount'),
    ('has_quantity', 'quantity'),
    ('has_reference', 'reference'),
    ('has_location', 'location'),
)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _ep_request_categories(self):
        """Kinds of request this employee may raise from the portal."""
        self.ensure_one()
        return self.env['approval.category'].sudo().search([
            ('ep_portal_available', '=', True),
            ('company_id', '=', self.company_id.id),
        ])

    def _ep_approval_requests(self, limit=None):
        self.ensure_one()
        return self.env['approval.request'].sudo().search(
            [('ep_employee_id', '=', self.id)], order='create_date desc, id desc', limit=limit)

    def _ep_day_start(self, day):
        """Midnight of `day` in the employee's time zone, in UTC as Odoo stores it."""
        tz = pytz.timezone(self.tz or DEFAULT_TZ)
        return tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)

    def _ep_create_approval_request(self, category, values, files=()):
        """Raise a request of `category` for this employee and submit it.

        `values`: subject, reason, date, date_start, date_end (dates),
        amount, quantity (numbers), reference, location (text)."""
        self.ensure_one()
        if category not in self._ep_request_categories():
            raise UserError(self.env._("This kind of request is not available."))
        if not self.user_id:
            raise UserError(self.env._("Your employee record has no user."))
        vals = {
            'category_id': category.id,
            'request_owner_id': self.user_id.id,
            'ep_employee_id': self.id,
            'name': (values.get('subject') or '').strip() or category.name,
        }
        reason = (values.get('reason') or '').strip()
        if reason:
            vals['reason'] = plaintext2html(reason)
        missing = []
        if category.has_date != 'no':
            if values.get('date'):
                vals['date'] = self._ep_day_start(values['date'])
            elif category.has_date == 'required':
                missing.append(self.env._("date"))
        if category.has_period != 'no':
            if values.get('date_start') and values.get('date_end'):
                vals['date_start'] = self._ep_day_start(values['date_start'])
                vals['date_end'] = self._ep_day_start(values['date_end'])
            elif category.has_period == 'required' or values.get('date_start') or values.get('date_end'):
                missing.append(self.env._("first and last day"))
        for switch, fname in SIMPLE_FIELDS:
            if category[switch] == 'no':
                continue
            value = values.get(fname)
            if value:
                vals[fname] = value
            elif category[switch] == 'required':
                missing.append(category._fields[switch].string.removeprefix('Has ').lower())
        if 'amount' in vals and vals['amount'] < 0:
            raise UserError(self.env._("The amount cannot be negative."))
        attachment_values = self._ep_prepare_attachments(files)
        if category.requirer_document == 'required' and not attachment_values:
            missing.append(self.env._("supporting document"))
        if missing:
            raise UserError(self.env._("Please fill in: %s.", ', '.join(missing)))

        approval = self.env['approval.request'].sudo().create(vals)
        if attachment_values:
            self.env['ir.attachment'].sudo().create([
                dict(v, res_model='approval.request', res_id=approval.id) for v in attachment_values
            ])
        if len(approval.approver_ids) < max(category.approval_minimum, 1):
            raise UserError(self.env._(
                "%s has no approver yet, so it cannot be sent. Please contact HR.", category.name))
        approval.action_confirm()
        return approval

    def _ep_cancel_approval_request(self, approval):
        self.ensure_one()
        approval = approval.sudo()
        if approval.ep_employee_id != self:
            raise UserError(self.env._("This is not your request."))
        if approval.request_status not in OPEN_REQUEST_STATES:
            raise UserError(self.env._("Only requests that are still waiting can be cancelled."))
        approval.approver_ids.write({'status': 'cancel'})
        approval._cancel_activities()
