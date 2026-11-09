from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    ep_portal_available = fields.Boolean(
        string="Available in Employee Portal",
        help="Employees can request this type of time off from the employee portal. "
             "Not possible for types without approval: a portal request always waits "
             "for an approver.")

    @api.constrains('ep_portal_available', 'leave_validation_type')
    def _check_ep_portal_available(self):
        if self.filtered(lambda t: t.ep_portal_available and t.leave_validation_type == 'no_validation'):
            raise ValidationError(self.env._(
                "A time off type with no approval cannot be available in the employee portal: "
                "employees would approve their own time off. Set an approval first."))

    def write(self, vals):
        # Switching a type to "No approval" takes it out of the portal.
        if vals.get('leave_validation_type') == 'no_validation' and 'ep_portal_available' not in vals:
            vals = dict(vals, ep_portal_available=False)
        return super().write(vals)

    @api.model
    def _ep_enable_used_types(self):
        """Make available in the portal the types the company already works with:
        types of a company, or with allocations or requests. Types with no
        approval are left out, they cannot be offered in the portal."""
        used_type_ids = set(self.env['hr.leave.allocation'].search([]).holiday_status_id.ids)
        used_type_ids |= set(self.env['hr.leave'].search([]).holiday_status_id.ids)
        self.search([
            ('leave_validation_type', '!=', 'no_validation'),
            '|', ('company_id', '!=', False), ('id', 'in', list(used_type_ids)),
        ]).ep_portal_available = True
