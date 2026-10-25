from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

STAGE_CODES = [
    ('new', 'New'),
    ('out_for_delivery', 'Out for Delivery'),
    ('delivered', 'Delivered'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled / Returned'),
]
# Stages after which an order is closed (no move out of them)
CLOSED_CODES = ('completed', 'cancelled')


class OnlineOrderStage(models.Model):
    _name = 'online.order.stage'
    _description = 'Online Order Stage'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    fold = fields.Boolean(string='Folded in Board')
    code = fields.Selection(
        STAGE_CODES,
        string='Role',
        copy=False,
        help="What Odoo does when an order enters this stage:\n"
             "- Out for Delivery: validates the delivery order (stock is deducted)"
             " and records the departure time.\n"
             "- Delivered: records the delivery time.\n"
             "- Completed: set automatically after closing.\n"
             "- Cancelled: only through the Cancel order button (reason required).\n"
             "Leave empty for an extra stage.",
    )
    mail_template_id = fields.Many2one(
        'mail.template',
        string='Email Template',
        domain=[('model', '=', 'sale.order')],
        help='Sent to the customer when an order enters this stage.',
    )
    activity_user_id = fields.Many2one(
        'res.users',
        string='Activity For',
        domain=[('share', '=', False)],
        help='When an order enters this stage, a To-Do activity is created for this user '
             '(e.g. the accountant on "Cancelled", for the refund).',
    )
    activity_summary = fields.Char(string='Activity Summary', translate=True)
    portal_label = fields.Char(
        string='Shown to Customer',
        translate=True,
        help='Delivery status shown in My Orders. Empty: the stage name.',
    )
    portal_color = fields.Selection(
        [('info', 'Blue'), ('warning', 'Orange'), ('success', 'Green'),
         ('danger', 'Red'), ('secondary', 'Grey')],
        string='Customer Badge Color',
        default='info',
    )

    @api.constrains('code', 'active')
    def _check_unique_code(self):
        for stage in self.filtered('code'):
            if self.search_count([('code', '=', stage.code), ('id', '!=', stage.id)]):
                raise ValidationError(_("Only one stage can have the role %s.", stage.code))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_role(self):
        if self.filtered('code'):
            raise UserError(_("Stages with a role cannot be deleted. You can rename them instead."))

    @api.model
    def _get_by_code(self, code):
        return self.search([('code', '=', code)], limit=1)

    def _position(self):
        self.ensure_one()
        return (self.sequence, self.id)

    def _is_at_or_after(self, other):
        """True if this stage is `other` or comes after it on the board."""
        self.ensure_one()
        return bool(other) and self._position() >= other._position()
