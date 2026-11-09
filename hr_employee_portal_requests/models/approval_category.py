from odoo import fields, models


class ApprovalCategory(models.Model):
    _inherit = 'approval.category'

    ep_portal_available = fields.Boolean(
        "Available in employee portal",
        help="Employees can raise this kind of request from their employee portal.")
