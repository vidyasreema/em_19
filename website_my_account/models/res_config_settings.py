from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    my_account_page = fields.Boolean(related='website_id.my_account_page', readonly=False)
