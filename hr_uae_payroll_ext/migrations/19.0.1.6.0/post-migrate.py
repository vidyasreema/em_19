from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """The company's own "UAE Monthly Salary" structure replaces the standard one:
    copy the accounts and move the draft payslips to it."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.payroll.structure']._uae_setup_monthly_structure()
