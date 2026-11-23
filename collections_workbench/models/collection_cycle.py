from odoo import api, fields, models


class CollectionCycle(models.Model):
    """A closed follow-up cycle, saved when the customer pays in full (BR-13)."""
    _name = 'collection.cycle'
    _description = 'Closed Collection Cycle'
    _order = 'date_end desc, id desc'

    partner_id = fields.Many2one('res.partner', string="Customer", required=True, index=True,
                                 ondelete='cascade')
    date_start = fields.Date(string="Start", required=True)
    date_end = fields.Date(string="End", required=True)
    days = fields.Integer(compute='_compute_days', store=True)
    max_stage_id = fields.Many2one('collection.stage', string="Highest stage reached")
    had_partial = fields.Boolean(string="Had a partial payment")
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    @api.depends('date_start', 'date_end')
    def _compute_days(self):
        for cycle in self:
            cycle.days = (cycle.date_end - cycle.date_start).days if cycle.date_start and cycle.date_end else 0
