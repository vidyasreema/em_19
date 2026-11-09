from . import controllers
from . import models
from . import report
from . import wizard


def _post_init_hook(env):
    env['hr.leave.type']._uae_archive_unused_types()
    env['resource.calendar']._uae_mark_full_days()
    env['hr.payroll.structure']._uae_setup_monthly_structure()
    env['hr.payroll.adjustment.type'].search([])._uae_setup_accounts()
