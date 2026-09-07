from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    raw_material_enforcement = fields.Selection(
        [
            ('force', 'Force - block order completion without raw materials'),
            ('warning', 'Warning - show a warning but allow continuation'),
            ('none', 'None - no validation'),
        ],
        string='Raw Material Enforcement',
        default='warning',
        help='Controls whether the person entering the order must specify '
             'raw materials for manufactured products before completing a '
             'POS order.',
    )

    mfg_review_user_id = fields.Many2one(
        'res.users',
        string='Manufacturing Review Responsible',
        help="User who receives the To-Do activity when a POS refund affects "
             "a Manufacturing Order that cannot be reversed automatically. "
             "Falls back to the Manufacturing Order's responsible if empty.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if fields_list:
            fields_list.append('raw_material_enforcement')
        return fields_list