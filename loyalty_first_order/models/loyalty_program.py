from odoo import fields, models


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    first_order_only = fields.Boolean(
        string="First Order Only",
        help="Only customers without any confirmed sales order can use this program. "
             "Draft / sent quotations are ignored. Next Order Coupons: only the first order "
             "earns a coupon; the coupon itself can be used on a later order.",
    )
