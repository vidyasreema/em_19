from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_raw_material_enforcement = fields.Selection(
        related='pos_config_id.raw_material_enforcement',
        readonly=False,
    )
    pos_mfg_review_user_id = fields.Many2one(
        related='pos_config_id.mfg_review_user_id',
        readonly=False,
    )
    pos_mfg_activity_creation = fields.Selection(
        related='pos_config_id.mfg_activity_creation',
        readonly=False,
    )
    pos_raw_material_tolerance = fields.Float(
        related='pos_config_id.raw_material_tolerance',
        readonly=False,
    )