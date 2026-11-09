from dateutil.relativedelta import relativedelta

from odoo import api, models
from odoo.exceptions import ValidationError


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def _get_durations(self, check_leave_type=True, resource_calendar=None):
        result = super()._get_durations(check_leave_type=check_leave_type, resource_calendar=resource_calendar)
        for leave in self:
            if (leave.id in result and leave.holiday_status_id.uae_count_calendar_days
                    and leave.leave_type_request_unit != 'hour'
                    and leave.request_date_from and leave.request_date_to):
                # Hours stay the working hours: work entries and payroll still use them.
                result[leave.id] = (leave._uae_calendar_days(), result[leave.id][1])
        return result

    def _uae_calendar_days(self, date_from=None, date_to=None):
        """Calendar days of this leave between two dates (the whole leave by
        default). On half-day types, starting in the afternoon or ending in the
        morning takes half a day off: a single morning is 0.5 day."""
        self.ensure_one()
        start = max(self.request_date_from, date_from or self.request_date_from)
        end = min(self.request_date_to, date_to or self.request_date_to)
        if end < start:
            return 0.0
        days = (end - start).days + 1
        if self.request_unit_half:
            if start == self.request_date_from and self.request_date_from_period == 'pm':
                days -= 0.5
            if end == self.request_date_to and self.request_date_to_period == 'am':
                days -= 0.5
        return max(days, 0.0)

    @api.constrains('holiday_status_id', 'request_date_from', 'employee_id')
    def _check_uae_min_service(self):
        for leave in self:
            months = leave.holiday_status_id.uae_min_service_months
            if not months or not leave.employee_id or not leave.request_date_from:
                continue
            available_from = leave.employee_id.sudo()._ep_join_date() + relativedelta(months=months)
            if leave.request_date_from < available_from:
                raise ValidationError(self.env._(
                    "%(type)s can be taken from %(date)s, after %(months)s months of service.",
                    type=leave.holiday_status_id.name, date=available_from, months=months))
