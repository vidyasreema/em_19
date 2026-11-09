import base64
import io

import xlsxwriter
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

BASIC_CODES = ('BASIC',)
ALLOWANCE_CODES = ('HOUALLOW', 'TRAALLOW', 'OTALLOW')
# Columns of the accountant's sheet, always shown: (key, label, rule codes they add up).
# Every other addition or deduction line gets its own column in the months it is used.
ADDITION_COLUMNS = [
    ('UAEARREAR', _lt("Arrear Salary"), ('UAEARREAR',)),
    ('UAECOMMISSION', _lt("Commission"), ('UAECOMMISSION',)),
    ('UAEGRAT', _lt("Gratuity"), ('UAEGRAT',)),
    ('BONUS', _lt("Bonus"), ('BONUS',)),
    ('UAELEAVEPAY', _lt("Leave"), ('UAELEAVEPAY',)),
    ('LOAN_PAID', _lt("Loan"), ()),
]
DEDUCTION_COLUMNS = [
    ('UAELOAN', _lt("Loan Install"), ('UAELOAN',)),
    ('UAEADVANCE', _lt("Advance"), ('UAEADVANCE',)),
    ('LEAVE', _lt("Leave"), ('UAEUNPAID', 'UAEHALFPAY', 'UAELEAVEDED')),
    ('UAEFINE', _lt("Fine"), ('UAEFINE',)),
    ('OTHER_DEDUCTIONS', _lt("Other Deduction"), ('OTHER_DEDUCTIONS',)),
]
ADDITION_KEYS = {code: key for key, _label, codes in ADDITION_COLUMNS for code in codes}
DEDUCTION_KEYS = {code: key for key, _label, codes in DEDUCTION_COLUMNS for code in codes}
# Categories (or parent categories) of the lines that make the net salary
NET_CATEGORIES = ('BASIC', 'ALW', 'DED')

MONEY = '#,##0.00;-#,##0.00;"-"'
FONT = 'Arial'
YELLOW, GREY, PEACH, GREEN = '#FFFF99', '#C0C0C0', '#FFCC99', '#92D050'
BLUE, RED = '#0000FF', '#FF0000'
FIRST_AMOUNT_COL = 4  # E: Basic Salaries


class HrPayrollSalarySheet(models.TransientModel):
    """The accountant's monthly salary sheet, as an Excel file: one row per
    payslip, grouped by department, with a column for each kind of addition
    and deduction, so every amount can be traced to its payslip line."""
    _name = 'hr.payroll.salary.sheet'
    _description = 'Monthly Salary Sheet'

    date_from = fields.Date(string="From", required=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string="To", required=True,
                          default=lambda self: fields.Date.context_today(self) + relativedelta(day=31))
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda self: self.env.company)
    include_draft = fields.Boolean(string="Include Draft Payslips", default=True,
                                   help="Draft payslips are marked (draft) after the employee's name.")
    file = fields.Binary(string="File", readonly=True, attachment=False)
    file_name = fields.Char(readonly=True)

    @api.onchange('date_from')
    def _onchange_date_from(self):
        if self.date_from:
            self.date_to = self.date_from + relativedelta(day=31)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _uae_payslips(self):
        self.ensure_one()
        states = ('draft', 'validated', 'paid') if self.include_draft else ('validated', 'paid')
        return self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', self.date_from),
            ('date_from', '<=', self.date_to),
            ('state', 'in', states),
        ])

    @api.model
    def _uae_net_category(self, category):
        while category:
            if category.code in NET_CATEGORIES:
                return category.code
            category = category.parent_id
        return False

    def _uae_sheet_data(self):
        """Rows grouped by department and the columns they need:
        {'additions': [(key, label)], 'deductions': [(key, label)], 'has_draft',
         'groups': [{'name', 'rows': [{'slip', 'permit', 'name', 'designation', 'basic',
                                       'allowances', 'additions': {key: amount},
                                       'deductions': {key: amount}, 'net'}]}]}
        Deductions are positive amounts: basic + allowances + additions - deductions
        is the net salary of the payslip."""
        self.ensure_one()
        extra = {'additions': {}, 'deductions': {}}
        groups = {}
        slips = self._uae_payslips()
        for slip in slips:
            employee = slip.employee_id
            row = {
                'slip': slip,
                'permit': employee.permit_no or '',
                'name': employee.name if slip.state != 'draft' else self.env._("%s (draft)", employee.name),
                'designation': employee.job_title or employee.job_id.name or '',
                'basic': 0.0, 'allowances': 0.0, 'additions': {}, 'deductions': {},
                'net': slip.net_wage,
            }
            for line in slip.line_ids:
                kind = self._uae_net_category(line.category_id)
                if not kind or not line.total:
                    continue
                if line.code in BASIC_CODES:
                    row['basic'] += line.total
                    continue
                if line.code in ALLOWANCE_CODES:
                    row['allowances'] += line.total
                    continue
                side, keys, amount = ('deductions', DEDUCTION_KEYS, -line.total) if kind == 'DED' \
                    else ('additions', ADDITION_KEYS, line.total)
                key = keys.get(line.code)
                if not key:
                    # A type HR added, or another line of the structure: its own column
                    key = line.code
                    extra[side].setdefault(key, (line.salary_rule_id.sequence, line.salary_rule_id.name or line.name))
                row[side][key] = row[side].get(key, 0.0) + amount
            groups.setdefault(employee.department_id, []).append(row)

        def columns(fixed_columns, side):
            return [(key, self.env._(label)) for key, label, _codes in fixed_columns] + [
                (key, label) for key, (_sequence, label) in sorted(extra[side].items(), key=lambda item: item[1])]

        return {
            'additions': columns(ADDITION_COLUMNS, 'additions'),
            'deductions': columns(DEDUCTION_COLUMNS, 'deductions'),
            'has_draft': any(slip.state == 'draft' for slip in slips),
            'groups': [{
                'name': department.name or self.env._("No Department"),
                'rows': sorted(groups[department], key=lambda r: r['slip'].employee_id.name or ''),
            } for department in sorted(groups, key=lambda d: (not d, d.name or ''))],
        }

    # ------------------------------------------------------------------
    # Excel file
    # ------------------------------------------------------------------

    def _uae_formats(self, book):
        def fmt(**props):
            return book.add_format({'font_name': FONT, 'font_size': 10, 'valign': 'vcenter', **props})

        head = {'bold': True, 'border': 1, 'text_wrap': True, 'align': 'center'}
        cell = {'border': 1, 'num_format': MONEY}
        return {
            'title': fmt(bold=True, font_size=16, font_color=BLUE, align='center'),
            'subtitle': fmt(bold=True, font_size=12, underline=1, align='center'),
            'note': fmt(italic=True, font_color=RED, align='center'),
            'head': fmt(bg_color=YELLOW, **head),
            'head_add': fmt(bg_color=GREY, font_color=BLUE, **head),
            'sub_add': fmt(bg_color=GREY, font_color=BLUE, underline=1, font_size=9, **head),
            'head_ded': fmt(bg_color=PEACH, font_color=RED, **head),
            'sub_ded': fmt(bg_color=PEACH, font_color=RED, font_size=9, **head),
            'group': fmt(bold=True, font_size=12, align='center', top=1, bottom=1),
            'sn': fmt(border=1, align='right'),
            'text': fmt(border=1),
            'money': fmt(**cell),
            'money_add': fmt(bg_color=GREY, **cell),
            'money_ded': fmt(bg_color=PEACH, **cell),
            'money_pay': fmt(bold=True, **cell),
            'subtotal_label': fmt(bold=True, bg_color=GREEN, border=1),
            'subtotal': fmt(bold=True, bg_color=GREEN, **cell),
            'total_label': fmt(bold=True, bg_color=YELLOW, border=2),
            'total': fmt(bold=True, bg_color=YELLOW, border=2, num_format=MONEY),
            'sign': fmt(bold=True, align='center', top=2, top_color=RED),
        }

    def _uae_month_label(self):
        if self.date_from.replace(day=1) == self.date_to.replace(day=1):
            return format_date(self.env, self.date_from, date_format='MMMM y').upper()
        return self.env._("%(start)s to %(end)s",
                          start=format_date(self.env, self.date_from), end=format_date(self.env, self.date_to))

    def _uae_xlsx(self):
        """The salary sheet as xlsx bytes. Totals are formulas (with their values,
        for viewers that do not recalculate)."""
        self.ensure_one()
        data = self._uae_sheet_data()
        additions, deductions = data['additions'], data['deductions']
        out = io.BytesIO()
        book = xlsxwriter.Workbook(out, {'in_memory': True})
        sheet = book.add_worksheet(self.env._("Salaries")[:31])
        f = self._uae_formats(book)

        # Columns: S/N, permit, name, designation, basic, allowances, total, additions,
        # deductions, total deductions, salary payable
        col_total = FIRST_AMOUNT_COL + 2
        col_add = col_total + 1
        col_ded = col_add + len(additions)
        col_ded_total = col_ded + len(deductions)
        col_pay = col_ded_total + 1
        widths = [5, 16, 30, 22, 12, 12, 12] + [12] * (len(additions) + len(deductions)) + [12, 14]
        for col, width in enumerate(widths):
            sheet.set_column(col, col, width)
        cell = xlsxwriter.utility.xl_rowcol_to_cell

        sheet.merge_range(1, 0, 1, col_pay, self.company_id.name.upper(), f['title'])
        sheet.merge_range(2, 0, 2, col_pay, self.env._("Salaries for the Month of %s", self._uae_month_label()),
                          f['subtitle'])
        if data['has_draft']:
            sheet.merge_range(3, 0, 3, col_pay, self.env._("Includes draft payslips: check them before paying."),
                              f['note'])

        # Header: two rows
        top, sub = 4, 5
        sheet.set_row(sub, 30)
        for col, label in enumerate([self.env._("S/N"), self.env._("Work Permit N#"), self.env._("Employee Name"),
                                     self.env._("Designation"), self.env._("Basic Salaries"),
                                     self.env._("Allowances"), self.env._("Total Salaries")]):
            sheet.merge_range(top, col, sub, col, label, f['head'])
        sheet.merge_range(top, col_add, top, col_ded - 1, self.env._("Additions"), f['head_add'])
        for index, (_key, label) in enumerate(additions):
            sheet.write(sub, col_add + index, label, f['sub_add'])
        sheet.merge_range(top, col_ded, top, col_ded_total, self.env._("Deductions"), f['head_ded'])
        for index, (_key, label) in enumerate(deductions):
            sheet.write(sub, col_ded + index, label, f['sub_ded'])
        sheet.write(sub, col_ded_total, self.env._("Total"), f['sub_ded'])
        sheet.merge_range(top, col_pay, sub, col_pay, self.env._("Salary Payable"), f['head'])
        sheet.freeze_panes(sub + 1, FIRST_AMOUNT_COL)
        sheet.repeat_rows(top, sub)

        row = sub + 1
        subtotal_rows = []
        grand_totals = {}
        for group in data['groups']:
            sheet.merge_range(row, 0, row, col_pay, group['name'], f['group'])
            row += 1
            first = row
            group_totals = {}
            for number, line in enumerate(group['rows'], start=1):
                total_salary = line['basic'] + line['allowances']
                ded_total = sum(line['deductions'].values())
                amounts = {
                    FIRST_AMOUNT_COL: line['basic'],
                    FIRST_AMOUNT_COL + 1: line['allowances'],
                    col_total: total_salary,
                    col_ded_total: ded_total,
                    col_pay: total_salary + sum(line['additions'].values()) - ded_total,
                }
                for index, (key, _label) in enumerate(additions):
                    amounts[col_add + index] = line['additions'].get(key, 0.0)
                for index, (key, _label) in enumerate(deductions):
                    amounts[col_ded + index] = line['deductions'].get(key, 0.0)

                sheet.write_number(row, 0, number, f['sn'])
                sheet.write(row, 1, line['permit'], f['text'])
                sheet.write(row, 2, line['name'], f['text'])
                sheet.write(row, 3, line['designation'], f['text'])
                for col in range(FIRST_AMOUNT_COL, col_total):
                    sheet.write_number(row, col, amounts[col], f['money'])
                for col in range(col_add, col_ded_total):
                    sheet.write_number(row, col, amounts[col], f['money_add'] if col < col_ded else f['money_ded'])
                sheet.write_formula(row, col_total, '=%s+%s' % (cell(row, FIRST_AMOUNT_COL), cell(row, FIRST_AMOUNT_COL + 1)),
                                    f['money'], amounts[col_total])
                sheet.write_formula(row, col_ded_total, '=SUM(%s:%s)' % (cell(row, col_ded), cell(row, col_ded_total - 1)),
                                    f['money_ded'], amounts[col_ded_total])
                sheet.write_formula(row, col_pay, '=%s+SUM(%s:%s)-%s' % (
                    cell(row, col_total), cell(row, col_add), cell(row, col_ded - 1), cell(row, col_ded_total)),
                    f['money_pay'], amounts[col_pay])
                for col, value in amounts.items():
                    group_totals[col] = group_totals.get(col, 0.0) + value
                row += 1

            for col in range(FIRST_AMOUNT_COL):
                sheet.write_blank(row, col, None, f['subtotal_label'])
            sheet.write(row, 3, self.env._("Sub total"), f['subtotal_label'])
            for col in range(FIRST_AMOUNT_COL, col_pay + 1):
                sheet.write_formula(row, col, '=SUM(%s:%s)' % (cell(first, col), cell(row - 1, col)),
                                    f['subtotal'], group_totals.get(col, 0.0))
                grand_totals[col] = grand_totals.get(col, 0.0) + group_totals.get(col, 0.0)
            subtotal_rows.append(row)
            row += 2

        if subtotal_rows:
            for col in range(FIRST_AMOUNT_COL):
                sheet.write_blank(row, col, None, f['total_label'])
            sheet.write(row, 3, self.env._("Grand total"), f['total_label'])
            for col in range(FIRST_AMOUNT_COL, col_pay + 1):
                sheet.write_formula(row, col, '=' + '+'.join(cell(r, col) for r in subtotal_rows),
                                    f['total'], grand_totals.get(col, 0.0))
            row += 4

        # Signatures
        sheet.merge_range(row, 1, row, 2, self.env._("Prepared by"), f['sign'])
        sheet.merge_range(row, max(col_pay - 3, 4), row, col_pay, self.env._("Chief Executive Officer"), f['sign'])

        sheet.set_landscape()
        sheet.set_paper(9)  # A4
        sheet.fit_to_pages(1, 0)
        sheet.set_margins(left=0.3, right=0.3, top=0.5, bottom=0.5)
        book.close()
        return out.getvalue()

    def action_download(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(self.env._("The end date is before the start date."))
        if not self._uae_payslips():
            raise UserError(self.env._("There are no payslips in this period."))
        name = self.env._("Salaries %s", self._uae_month_label().title())
        self.write({'file': base64.b64encode(self._uae_xlsx()), 'file_name': '%s.xlsx' % name.replace('/', '-')})
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/file/%s?download=true' % (self._name, self.id, self.file_name),
            'target': 'self',
        }
