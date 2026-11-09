from odoo import fields, models


class HrLeaveAllocation(models.Model):
    _inherit = 'hr.leave.allocation'

    uae_contract_start = fields.Date(
        string="Contract Start", readonly=True, copy=False,
        help="Start of the contract this allocation was given for (days per contract).")
