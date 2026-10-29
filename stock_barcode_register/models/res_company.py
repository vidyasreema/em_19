from odoo import fields, models


def _followup_user_domain(self):
    # Internal users who can open the receipt or delivery the Activity points to
    return [('share', '=', False), ('all_group_ids', 'in', self.env.ref('stock.group_stock_user').ids)]


class ResCompany(models.Model):
    _inherit = 'res.company'

    barcode_register_tolerance = fields.Float('Difference Tolerance (%)', default=0.5)
    barcode_register_followup_user_ids = fields.Many2many(
        'res.users', 'res_company_barcode_register_followup_rel', 'company_id', 'user_id',
        string='Difference Follow-up Responsible', domain=_followup_user_domain)
    barcode_alert_days_fresh = fields.Integer('Alert Age Fresh (days)', default=7)
    barcode_alert_days_chilled = fields.Integer('Alert Age Chilled (days)', default=80)
    barcode_alert_days_frozen = fields.Integer('Alert Age Frozen (days)', default=270)
