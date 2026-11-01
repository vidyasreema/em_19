from odoo import fields, models

from .res_company import _followup_user_domain


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    barcode_register_tolerance = fields.Float(related='company_id.barcode_register_tolerance', readonly=False)
    barcode_register_followup_user_ids = fields.Many2many(
        related='company_id.barcode_register_followup_user_ids', readonly=False, domain=_followup_user_domain)
    barcode_alert_days_fresh = fields.Integer(related='company_id.barcode_alert_days_fresh', readonly=False)
    barcode_alert_days_chilled = fields.Integer(related='company_id.barcode_alert_days_chilled', readonly=False)
    barcode_alert_days_frozen = fields.Integer(related='company_id.barcode_alert_days_frozen', readonly=False)
