from odoo import api, fields, models


class ResPartnerInherit(models.Model):
    _inherit = "res.partner"

    sales_man = fields.Many2one('hr.employee', string="Sales Man")

    def get_sales_man_data(self):
        MAPPING = {
            'Romeo': 'Romeo Jr. Ramos Macabenta',
            'Jamil': 'JamilleYsel Crom Nebrida',
            'Nahas': 'NAHAS CHOMBALAN AMOO NALUPURAPPATTIL THEKKE PURAYIL',
        }

        # If called with no records selected, run on ALL partners
        records = self if self else self.env['res.partner'].search([
            ('x_studio_sales_man', '!=', False)
        ])

        for rec in records:
            if rec.x_studio_sales_man and rec.x_studio_sales_man.strip() in MAPPING:
                required_name = MAPPING[rec.x_studio_sales_man.strip()]
                # Use ilike instead of = to avoid case/space mismatches
                employee = self.env['hr.employee'].search([
                    ('name', 'ilike', required_name.strip()),
                ], limit=1)
                rec.sales_man = employee.id if employee else False