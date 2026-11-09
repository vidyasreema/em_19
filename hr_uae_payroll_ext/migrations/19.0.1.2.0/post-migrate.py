from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Sick leave: the full yearly days for employees who joined during the
    year, instead of a prorata. Replay the sick accrual allocations from
    1 January of the join year."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    allocations = env['hr.leave.allocation'].search([
        ('allocation_type', '=', 'accrual'),
        ('accrual_plan_id', 'in', [
            env.ref(xmlid).id for xmlid in (
                'hr_uae_payroll_ext.accrual_plan_sick_full',
                'hr_uae_payroll_ext.accrual_plan_sick_half',
                'hr_uae_payroll_ext.accrual_plan_sick_unpaid',
            ) if env.ref(xmlid, raise_if_not_found=False)
        ]),
        ('state', '=', 'validate'),
    ])
    for allocation in allocations:
        date_from = allocation.date_from.replace(month=1, day=1)
        allocation.write({
            'date_from': date_from, 'lastcall': date_from, 'nextcall': False,
            'number_of_days': 0, 'already_accrued': False,
            'last_executed_carryover_date': False, 'yearly_accrued_amount': 0,
        })
    allocations._process_accrual_plans()
