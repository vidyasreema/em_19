from odoo import _, api, fields, models


class CollectionAssignWizard(models.TransientModel):
    """Change the collections assignee of several customers at once
    (table bulk action, as in the simulation)."""
    _name = 'collection.assign.wizard'
    _description = 'Collections: change assignee'

    line_ids = fields.Many2many('collection.snapshot.line', string="Customers")
    line_count = fields.Integer(compute='_compute_line_count')
    allowed_employee_ids = fields.Many2many('hr.employee', compute='_compute_allowed_employee_ids')
    employee_id = fields.Many2one(
        'hr.employee', string="New assignee", domain="[('id', 'in', allowed_employee_ids)]",
        help="Empty = back to the Sales man on the customer card.")

    @api.depends('line_ids')
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids.partner_id)

    @api.depends_context('company')
    def _compute_allowed_employee_ids(self):
        employees = self.env.company.collection_employee_ids or self.env['hr.employee'].search(
            [('company_id', 'in', [False, self.env.company.id])])
        for wizard in self:
            wizard.allowed_employee_ids = employees

    def action_confirm(self):
        self.ensure_one()
        self.line_ids.write({'assignee_id': self.employee_id.id or False})
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'message': _("Assignee updated for %s customers: they were notified in their Inbox.",
                             self.line_count),
                'type': 'success', 'next': {'type': 'ir.actions.act_window_close'},
            },
        }
