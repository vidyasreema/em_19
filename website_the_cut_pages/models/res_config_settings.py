from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cut_pages_enabled = fields.Boolean(related='website_id.cut_pages_enabled', readonly=False)
    cut_care_email = fields.Char(related='website_id.cut_care_email', readonly=False)
    cut_retention_period = fields.Char(related='website_id.cut_retention_period', readonly=False)
    cut_policies_date = fields.Date(related='website_id.cut_policies_date', readonly=False)
    cut_damaged_box_note = fields.Boolean(related='website_id.cut_damaged_box_note', readonly=False)
