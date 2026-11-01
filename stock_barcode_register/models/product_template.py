from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    storage_type = fields.Selection([
        ('fresh', 'Fresh'),
        ('chilled', 'Chilled'),
        ('frozen', 'Frozen'),
    ], string='Storage Type', help="Sets the default alert age of cartons.")
    barcode_alert_days = fields.Integer(
        'Alert Age (days)',
        help="Days added to the pack date to compute the alert date. Leave 0 to use the storage type default.")
    barcode_register_count = fields.Integer('Unsold Cartons', compute='_compute_barcode_register_stats')
    barcode_register_qty = fields.Float('Unsold Carton Quantity', compute='_compute_barcode_register_stats', digits='Product Unit')

    def _compute_barcode_register_stats(self):
        data = self.env['stock.barcode.register']._read_group(
            [('product_tmpl_id', 'in', self.ids), ('state', '=', 'unsold')],
            ['product_tmpl_id'], ['carton_count:sum', 'quantity:sum'],
        )
        stats = {tmpl.id: (cartons, qty) for tmpl, cartons, qty in data}
        for tmpl in self:
            tmpl.barcode_register_count, tmpl.barcode_register_qty = stats.get(tmpl.id, (0, 0.0))

    def action_open_barcode_register(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('stock_barcode_register.action_stock_barcode_register')
        action['domain'] = [('product_tmpl_id', '=', self.id)]
        action['context'] = {'search_default_group_by_picking': 1}
        return action

    def _get_barcode_alert_days(self, company):
        self.ensure_one()
        if self.barcode_alert_days:
            return self.barcode_alert_days
        return {
            'fresh': company.barcode_alert_days_fresh,
            'chilled': company.barcode_alert_days_chilled,
            'frozen': company.barcode_alert_days_frozen,
        }.get(self.storage_type, 0)
