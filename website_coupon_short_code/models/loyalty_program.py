import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.website_purchase_journey.models.loyalty_card import PERSONAL_PROGRAM_TYPES

SHORT_CODE_RE = re.compile(r'^[A-Z0-9-]{3,20}$')


def normalize_short_code(code):
    return (code or '').strip().upper()


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    short_code = fields.Char(
        string='Code Shown to Customers', copy=False,
        help="One short code for all the coupons of this programme (e.g. SECOND10). Customers see it "
             "instead of their long coupon code; typed by a signed-in customer, it applies their own "
             "coupon of this programme. It gives no discount by itself. Empty: the long code is shown.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('short_code'):
                vals['short_code'] = normalize_short_code(vals['short_code'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('short_code'):
            vals['short_code'] = normalize_short_code(vals['short_code'])
        return super().write(vals)

    @api.constrains('short_code', 'program_type')
    def _check_short_code(self):
        for program in self.filtered('short_code'):
            code = program.short_code
            if program.program_type not in PERSONAL_PROGRAM_TYPES:
                raise ValidationError(_(
                    "A code shown to customers is only for coupon programmes (Coupons, Next Order Coupons)."))
            if not SHORT_CODE_RE.match(code):
                raise ValidationError(_(
                    "The code shown to customers has 3 to 20 letters, digits or dashes (e.g. SECOND10)."))
            if self.with_context(active_test=False).search_count(
                    [('id', '!=', program.id), ('short_code', '=', code)], limit=1):
                raise ValidationError(_("%s is already the code shown for another programme.", code))
            if self.env['loyalty.rule'].sudo().with_context(active_test=False).search_count(
                    [('code', '=ilike', code)], limit=1) \
                    or self.env['loyalty.card'].sudo().search_count([('code', '=ilike', code)], limit=1):
                raise ValidationError(_("%s is already a real promotion or coupon code: choose another one.", code))

    @api.model
    def _short_code_program(self, code):
        """The programme whose code shown to customers is this code (any case)."""
        code = normalize_short_code(code)
        if not SHORT_CODE_RE.match(code):
            return self.browse()
        return self.sudo().search([('short_code', '=', code)], limit=1)


class LoyaltyRule(models.Model):
    _inherit = 'loyalty.rule'

    @api.constrains('code')
    def _check_code_not_short_code(self):
        for rule in self.filtered('code'):
            if self.env['loyalty.program'].sudo().with_context(active_test=False).search_count(
                    [('short_code', '=', normalize_short_code(rule.code))], limit=1):
                raise ValidationError(_(
                    "%s is the code shown to customers of a coupon programme: choose another one.", rule.code))
