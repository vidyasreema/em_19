from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    online_orders_email_from = fields.Char(related='website_id.online_orders_email_from', readonly=False)
