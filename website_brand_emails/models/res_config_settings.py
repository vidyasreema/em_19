from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    brand_emails = fields.Boolean(related='website_id.brand_emails', readonly=False)
