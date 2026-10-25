from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    journey_enabled = fields.Boolean(related='website_id.journey_enabled', readonly=False)
    journey_general_promise = fields.Char(related='website_id.journey_general_promise', readonly=False)
    journey_welcome_program_id = fields.Many2one(related='website_id.journey_welcome_program_id', readonly=False)
    journey_whatsapp_number = fields.Char(related='website_id.journey_whatsapp_number', readonly=False)
