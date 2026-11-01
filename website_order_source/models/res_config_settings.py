from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    order_source_question = fields.Boolean(related='website_id.order_source_question', readonly=False)
