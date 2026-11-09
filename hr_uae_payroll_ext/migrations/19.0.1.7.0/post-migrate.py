from odoo import SUPERUSER_ID, api

HALF_DAY_TYPES = (
    'hr_uae_payroll_ext.leave_type_annual',
    'hr_uae_payroll_ext.leave_type_sick_full',
    'hr_uae_payroll_ext.leave_type_sick_half',
    'hr_uae_payroll_ext.leave_type_sick_unpaid',
    'hr_uae_payroll_ext.leave_type_unpaid',
)


def migrate(cr, version):
    """Annual, sick and unpaid leave can be taken in half days. The leave types
    are noupdate, so set it here on existing databases. Existing leaves get their
    dates recomputed (to the same values): approved ones must not be blocked.
    Work schedules first, so that a day entered as one "Morning" line keeps its
    afternoon hours."""
    env = api.Environment(cr, SUPERUSER_ID, {'leave_skip_state_check': True, 'tracking_disable': True})
    env['resource.calendar']._uae_mark_full_days()
    for xmlid in HALF_DAY_TYPES:
        leave_type = env.ref(xmlid, raise_if_not_found=False)
        if leave_type and leave_type.request_unit == 'day':
            leave_type.request_unit = 'half_day'
    # Recompute the leaves now, with this context: a later flush would not have it.
    env.flush_all()
