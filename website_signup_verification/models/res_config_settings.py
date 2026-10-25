from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    signup_verification = fields.Boolean(related='website_id.signup_verification', readonly=False)
    signup_coupon_program_id = fields.Many2one(related='website_id.signup_coupon_program_id', readonly=False)
    login_social_first = fields.Boolean(related='website_id.login_social_first', readonly=False)
