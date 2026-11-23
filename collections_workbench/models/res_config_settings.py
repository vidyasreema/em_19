from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    collection_grace_days = fields.Integer(related='company_id.collection_grace_days', readonly=False)
    collection_keep_ratio = fields.Integer(related='company_id.collection_keep_ratio', readonly=False)
    collection_repeat_broken = fields.Integer(related='company_id.collection_repeat_broken', readonly=False)
    collection_chronic_broken = fields.Integer(related='company_id.collection_chronic_broken', readonly=False)
    collection_chronic_days = fields.Integer(related='company_id.collection_chronic_days', readonly=False)
    collection_unreach_streak = fields.Integer(related='company_id.collection_unreach_streak', readonly=False)
    collection_pattern_window = fields.Integer(related='company_id.collection_pattern_window', readonly=False)
    collection_partial_enabled = fields.Boolean(related='company_id.collection_partial_enabled', readonly=False)
    collection_partial_wait = fields.Integer(related='company_id.collection_partial_wait', readonly=False)
    collection_employee_ids = fields.Many2many(related='company_id.collection_employee_ids', readonly=False)
    collection_sender_email = fields.Char(related='company_id.collection_sender_email', readonly=False)
    collection_agreement_tag_ids = fields.Many2many(related='company_id.collection_agreement_tag_ids', readonly=False)
    collection_court_tag_ids = fields.Many2many(related='company_id.collection_court_tag_ids', readonly=False)
    collection_blacklist_tag_ids = fields.Many2many(related='company_id.collection_blacklist_tag_ids', readonly=False)
    collection_vip_tag_ids = fields.Many2many(related='company_id.collection_vip_tag_ids', readonly=False)
