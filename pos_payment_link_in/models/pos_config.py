from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    payment_link_in_enabled = fields.Boolean(
        string="Enable Payment Link In",
    )
    payment_link_in_journal_id = fields.Many2one(
        'account.journal',
        string="Payment Link In Journal",
        domain="[('type', 'in', ('bank', 'cash'))]",
    )