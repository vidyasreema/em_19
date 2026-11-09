from odoo import SUPERUSER_ID, api

from odoo.addons.hr_uae_payroll_ext.models.hr_payroll_structure import ACCOUNT_FIELDS


def migrate(cr, version):
    """Salary advances got their own payslip line: it starts with the accounts
    of the loan line, in each company."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Rule = env['hr.salary.rule']
    fnames = [f for f in ACCOUNT_FIELDS if f in Rule._fields]
    if 'account_debit' not in fnames:
        return
    for company in env['res.company'].search([]):
        loan = env.ref('hr_uae_payroll_ext.salary_rule_loan_recovery').with_company(company)
        advance = env.ref('hr_uae_payroll_ext.salary_rule_advance_recovery').with_company(company)
        if not (advance.account_debit or advance.account_credit) and (loan.account_debit or loan.account_credit):
            advance.write({fname: loan._fields[fname].convert_to_write(loan[fname], loan) for fname in fnames})
