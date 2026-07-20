from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_payment_link_in_enabled = fields.Boolean(
        related='pos_config_id.payment_link_in_enabled',
        readonly=False,
    )
    pos_payment_link_in_journal_id = fields.Many2one(
        related='pos_config_id.payment_link_in_journal_id',
        readonly=False,
    )