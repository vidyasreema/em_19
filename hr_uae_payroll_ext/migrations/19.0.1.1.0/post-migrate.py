from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Annual leave changes from a monthly accrual to 60 days per contract.
    Replace the monthly accrual allocations (unused ones only) and the plan,
    then give every employee the days of their current contract."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    annual = env.ref('hr_uae_payroll_ext.leave_type_annual', raise_if_not_found=False)
    if not annual:
        return
    # noupdate data: set the new values here.
    annual.write({'uae_days_per_contract': 60, 'uae_min_service_months': 0})

    plan = env.ref('hr_uae_payroll_ext.accrual_plan_annual', raise_if_not_found=False)
    if plan:
        allocations = env['hr.leave.allocation'].search([('accrual_plan_id', '=', plan.id)])
        unused = allocations.filtered(lambda a: not a.leaves_taken)
        unused.filtered(lambda a: a.state != 'refuse').action_refuse()
        unused.unlink()
        if allocations - unused:
            plan.active = False
        else:
            plan.level_ids.unlink()
            plan.unlink()

    env['hr.employee'].search([])._uae_create_contract_allocations()
