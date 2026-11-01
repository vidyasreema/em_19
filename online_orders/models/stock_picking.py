from odoo import _, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _online_set_delivered_by(self):
        """stock_barcode_register (when installed) requires a "Delivered by"
        employee to validate a delivery. Keep the one set by the warehouse,
        otherwise use the employee of the person moving the order to
        Out for Delivery, if that employee is authorized for operations."""
        field = self._fields.get('employee_id')
        if not field or field.comodel_name != 'hr.employee' \
                or 'stock_operation_authorized' not in self.env['hr.employee']._fields:
            return
        for picking in self.filtered(lambda p: not p.employee_id):
            employee = self.env.user.sudo().employee_ids.filtered(
                lambda e: e.stock_operation_authorized and e.company_id in (picking.company_id, False))[:1]
            if not employee:
                raise UserError(_(
                    "%(picking)s needs “Delivered by” before it can be validated, and your user "
                    "is not linked to an employee authorized for operations.\n\n"
                    "Either set “Delivered by” on %(picking)s, or tick “Authorized for Operations” "
                    "on your employee (Employees > your employee).",
                    picking=picking.name))
            picking.employee_id = employee
