from collections import defaultdict

from odoo import api, models


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    @api.model
    def _uae_mark_full_days(self):
        """Half-day leave splits "Full Day" attendances at their middle. A working
        day entered as one long "Morning" line (e.g. 9:00-18:00) has no afternoon,
        so half days and the end time of leave would be wrong: make it "Full Day".
        It already counts as one day, so durations do not change. Short
        morning-only days stay as they are."""
        Attendance = self.env['resource.calendar.attendance']
        days = defaultdict(lambda: Attendance)
        for attendance in Attendance.search([('display_type', '=', False), ('day_period', '!=', 'lunch')]):
            days[attendance.calendar_id, attendance.dayofweek, attendance.week_type] |= attendance
        single_mornings = Attendance.browse([
            lines.id for lines in days.values()
            if len(lines) == 1 and lines.day_period == 'morning'
            and lines.duration_hours > lines.calendar_id.hours_per_day * 3 / 4
        ])
        single_mornings.day_period = 'full_day'
        return single_mornings
