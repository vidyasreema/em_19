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
    mfg_activity_creation = fields.Selection(
        [
            ('always', 'Always - including actions handled automatically'),
            ('review_only', 'Only when manual review is needed'),
            ('never', 'Never - record in the chatter only'),
        ],
        string='Create Review Activity',
        default='review_only',
        required=True,
        help="When a POS refund affects a Manufacturing Order, decides "
             "whether a To-Do activity is raised for the Manufacturing "
             "Review Responsible.\n\n"
             "Always: also for refunds handled automatically, such as a "
             "cancelled Manufacturing Order or a validated Unbuild Order, "
             "so every case leaves a task behind.\n\n"
             "Only when manual review is needed: partial refunds, "
             "production that has already started, and unbuild orders that "
             "could not be validated.\n\n"
             "Never: nothing is assigned to anyone. Every action is still "
             "written to the Manufacturing Order's chatter.",
    )
    raw_material_tolerance = fields.Float(
        string='Raw Material Tolerance',
        default=0.1,
        digits='Product Unit of Measure',
        help="How far the raw material total may differ from the quantity "
             "sold before the cashier is stopped or warned, expressed in the "
             "finished product's unit of measure (0.1 = 100 g for products "
             "sold by the kilo).\n\n"
             "Above the sold quantity plus this tolerance the order is "
             "blocked; below the sold quantity minus this tolerance the "
             "cashier is warned but may continue. Set to 0 to require an "
             "exact match.\n\n"
             "The comparison is skipped entirely when the raw materials "
             "cannot be converted into the finished product's unit — for "
             "example meat measured in kg used for a product sold in Units.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if fields_list:
            fields_list.append('raw_material_enforcement')
            fields_list.append('raw_material_tolerance')
        return fields_list