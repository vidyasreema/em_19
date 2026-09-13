from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    pos_manufacturing_order_ids = fields.Many2many(
        'mrp.production',
        string='Manufacturing Orders',
        compute='_compute_pos_manufacturing_orders',
    )
    pos_manufacturing_order_count = fields.Integer(
        string='Manufacturing Order Count',
        compute='_compute_pos_manufacturing_orders',
    )

    @api.depends('pos_order_ids')
    def _compute_pos_manufacturing_orders(self):
        # sudo: accountants opening an invoice normally have no
        # Manufacturing rights, and the smart button must never block
        # the form from loading.
        for move in self:
            productions = move.sudo().pos_order_ids.manufacturing_order_ids
            move.pos_manufacturing_order_ids = productions
            move.pos_manufacturing_order_count = len(productions)

    def action_view_pos_manufacturing_orders(self):
        self.ensure_one()
        productions = self.sudo().pos_order_ids.manufacturing_order_ids
        action = self.env['ir.actions.act_window']._for_xml_id(
            'mrp.mrp_production_action'
        )
        action['domain'] = [('id', 'in', productions.ids)]
        action['context'] = {}
        if len(productions) == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = productions.id
        return action