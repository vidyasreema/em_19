import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .hr_payroll_structure import ACCOUNT_FIELDS

# Category, sequence and amount of the payslip line of each kind
KIND_RULES = {
    'addition': ('hr_payroll.ALW', 45, "result = inputs['%s'].amount"),
    'deduction': ('hr_payroll.DED', 69, "result = -inputs['%s'].amount"),
}
# Rule whose accounts a new type's line starts with
KIND_ACCOUNT_SOURCE = {
    'addition': 'hr_uae_payroll_ext.monthly_rule_bonus',
    'deduction': 'hr_uae_payroll_ext.monthly_rule_other_deductions',
}
CODE_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]*$')


class HrPayrollAdjustmentType(models.Model):
    """A kind of bonus or deduction (Bonus, Arrear salary, Commission, Fine...).
    Each type has its own payslip input and salary rule in the UAE monthly
    structure, created with the type, so every type is its own line on the
    payslip, in the accounting entry and in the salary sheet."""
    _name = 'hr.payroll.adjustment.type'
    _description = 'Bonus or Deduction Type'
    _order = 'kind, sequence, id'

    name = fields.Char(string="Name", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    kind = fields.Selection([
        ('addition', "Addition"),
        ('deduction', "Deduction"),
    ], string="Kind", required=True, default='addition',
        help="Additions are added to the salary, deductions are taken off.")
    code = fields.Char(string="Code", copy=False,
                       help="Code of its payslip line, made from the name when left empty.")
    is_fine = fields.Boolean(string="Fine Limit Check",
                             help="Warn when the fines of a month go above the days of salary set in Payroll settings.")
    input_type_id = fields.Many2one('hr.payslip.input.type', string="Payslip Input", readonly=True, copy=False,
                                    ondelete='restrict')
    rule_id = fields.Many2one('hr.salary.rule', string="Payslip Line", readonly=True, copy=False,
                              ondelete='restrict')

    _code_unique = models.Constraint('UNIQUE(code)', "Another type already has this code.")

    @api.constrains('code')
    def _check_code(self):
        for adjustment_type in self:
            if not CODE_PATTERN.match(adjustment_type.code or ''):
                raise ValidationError(self.env._(
                    "The code may only hold capital letters, digits and _ and must start with a letter."))

    def _uae_free_code(self, name):
        """A code from `name` not used by a rule of the monthly structure or an input type."""
        base = re.sub(r'[^A-Z0-9]+', '_', (name or '').upper()).strip('_') or 'ADJUSTMENT'
        if not base[0].isalpha():
            base = 'ADJ_' + base
        monthly = self.env.ref('hr_uae_payroll_ext.structure_uae_monthly')
        used = set(monthly.rule_ids.mapped('code')) | set(self.env['hr.payslip.input.type'].search([]).mapped('code')) \
            | set(self.with_context(active_test=False).search([]).mapped('code'))
        code, index = base, 2
        while code in used:
            code, index = '%s_%s' % (base, index), index + 1
        return code

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self._uae_free_code(vals.get('name'))
        types = super().create(vals_list)
        types.filtered(lambda t: not t.rule_id)._uae_create_payslip_line()
        return types

    def write(self, vals):
        if 'code' in vals and any(t.code != vals['code'] for t in self):
            raise UserError(self.env._("The code of a type cannot be changed: its payslip line uses it."))
        if 'kind' in vals and any(t.kind != vals['kind'] for t in self) \
                and self.env['hr.payroll.adjustment'].search_count([('type_id', 'in', self.ids)], limit=1):
            raise UserError(self.env._("This type is already used: create a new type instead of changing its kind."))
        result = super().write(vals)
        if 'name' in vals:
            for adjustment_type in self:
                adjustment_type.rule_id.sudo().name = adjustment_type.name
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_if_unused(self):
        if self.env['hr.payroll.adjustment'].with_context(active_test=False).search_count(
                [('type_id', 'in', self.ids)], limit=1):
            raise UserError(self.env._("This type is used by bonuses or deductions: archive it instead."))

    def _uae_create_payslip_line(self):
        """Payslip input and salary rule of the monthly structure for new types."""
        monthly = self.env.ref('hr_uae_payroll_ext.structure_uae_monthly')
        for adjustment_type in self.sudo():
            category, sequence, amount = KIND_RULES[adjustment_type.kind]
            input_type = self.env['hr.payslip.input.type'].create({
                'name': adjustment_type.name,
                'code': adjustment_type.code,
                'country_id': self.env.ref('base.ae').id,
                'struct_ids': [fields.Command.link(monthly.id)],
            })
            adjustment_type.write({
                'input_type_id': input_type.id,
                'rule_id': self.env['hr.salary.rule'].create({
                    'name': adjustment_type.name,
                    'code': adjustment_type.code,
                    'struct_id': monthly.id,
                    'category_id': self.env.ref(category).id,
                    'sequence': sequence,
                    'condition_select': 'input',
                    'condition_other_input_id': input_type.id,
                    'amount_select': 'code',
                    'amount_python_compute': amount % adjustment_type.code,
                }).id,
            })
        self._uae_setup_accounts()

    def _uae_setup_accounts(self):
        """Payslip lines without accounts take those of the Bonus line (additions)
        or of the Other Deduction line (deductions), in each company."""
        Rule = self.env['hr.salary.rule']
        fnames = [f for f in ACCOUNT_FIELDS if f in Rule._fields]
        if 'account_debit' not in fnames:
            return
        for company in self.env['res.company'].search([]):
            for adjustment_type in self.sudo().with_company(company):
                rule = adjustment_type.rule_id
                source = self.env.ref(KIND_ACCOUNT_SOURCE[adjustment_type.kind]).with_company(company)
                if rule and rule != source and not (rule.account_debit or rule.account_credit) \
                        and (source.account_debit or source.account_credit):
                    rule.write({fname: source._fields[fname].convert_to_write(source[fname], source)
                                for fname in fnames})

    def action_open_rule(self):
        """The payslip line, to set its accounts."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.salary.rule',
            'res_id': self.rule_id.id,
            'view_mode': 'form',
        }
