from odoo import api, models

# Accounting fields of hr_payroll_account, copied from the standard UAE rules.
ACCOUNT_FIELDS = (
    'account_debit', 'account_credit', 'not_computed_in_net', 'debit_tag_ids', 'credit_tag_ids',
    'split_move_lines', 'employee_move_line', 'batch_payroll_move_lines', 'analytic_distribution',
)
# Rule of the company structure -> rule of the standard structure it replaces.
STANDARD_CODES = {'UAEGRAT': 'EOS', 'UAELEAVEPAY': 'ALEA', 'UAELEAVEDED': 'ALED', 'UAEUNPAID': 'AEUNPAID'}


class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    @api.model
    def _uae_setup_monthly_structure(self):
        """Make the company structure the default one of the UAE structure type
        (set in code: the type is noupdate data of l10n_ae_hr_payroll), copy the
        accounts of the standard UAE rules to the matching rules of the company
        structure (for each company: they are company dependent), and move the
        draft payslips to the company structure."""
        standard = self.env.ref('l10n_ae_hr_payroll.uae_employee_payroll_structure')
        monthly = self.env.ref('hr_uae_payroll_ext.structure_uae_monthly')
        monthly.type_id.default_struct_id = monthly
        Rule = self.env['hr.salary.rule'].with_context(active_test=False)
        fnames = [f for f in ACCOUNT_FIELDS if f in Rule._fields]
        if fnames:
            standard_rules = Rule.search([('struct_id', '=', standard.id)])
            for company in self.env['res.company'].search([]):
                # A code can have several rules (e.g. an archived copy holding the
                # accounts): take the one with accounts, active first.
                by_code = {}
                for rule in standard_rules.with_company(company).sorted(
                        lambda r: (bool(r.account_debit or r.account_credit), r.active)):
                    by_code[rule.code] = rule
                for rule in monthly.with_company(company).rule_ids:
                    source = by_code.get(STANDARD_CODES.get(rule.code, rule.code))
                    if source:
                        rule.write({fname: source._fields[fname].convert_to_write(source[fname], source)
                                    for fname in fnames})
        self.env['hr.payslip'].search([
            ('struct_id', '=', standard.id), ('state', '=', 'draft'),
        ]).struct_id = monthly
