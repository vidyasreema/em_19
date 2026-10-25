from odoo import fields, models


class WebsiteOrderSource(models.Model):
    """An answer to "How did you hear about us?" (confirmation page)."""
    _name = 'website.order.source'
    _description = 'Order Source (How did you hear about us?)'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    order_count = fields.Integer('Orders', compute='_compute_order_count')

    def _compute_order_count(self):
        counts = dict(self.env['sale.order']._read_group(
            [('order_source_id', 'in', self.ids)], ['order_source_id'], ['__count']))
        for source in self:
            source.order_count = counts.get(source, 0)
