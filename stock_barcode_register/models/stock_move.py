from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockMove(models.Model):
    _inherit = 'stock.move'

    carton_ids = fields.One2many('stock.move.carton', 'move_id', 'Scanned Cartons')
    carton_count = fields.Integer('Cartons', compute='_compute_carton_count')
    barcode_difference = fields.Float(
        'Difference (%)', compute='_compute_barcode_difference', digits=(16, 2),
        help="Percentage difference between the actual quantity and the demand.")
    barcode_above_tolerance = fields.Boolean(compute='_compute_barcode_difference')
    barcode_difference_validated = fields.Float('Difference at Validation (%)', digits=(16, 2), copy=False, readonly=True)
    barcode_note = fields.Char('Note', copy=False, help="Required when the difference exceeds the tolerance.")
    photo_count = fields.Integer(compute='_compute_photo_count')
    count_session_id = fields.Many2one('stock.count.session', 'Count Session', readonly=True, copy=False, index='btree_not_null')
    count_session_diff = fields.Float('Change after Count Posting', digits='Product Unit', readonly=True, copy=False)
    barcode_register_logged = fields.Boolean(copy=False, readonly=True, index=True)

    @api.depends('carton_ids.carton_count')
    def _compute_carton_count(self):
        for move in self:
            move.carton_count = sum(move.carton_ids.mapped('carton_count'))

    def _compute_photo_count(self):
        data = self.env['ir.attachment']._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids), ('mimetype', '=like', 'image/%')],
            ['res_id'], ['__count'])
        counts = dict(data)
        for move in self:
            move.photo_count = counts.get(move.id, 0)

    @api.depends('quantity', 'product_uom_qty', 'state', 'barcode_difference_validated')
    def _compute_barcode_difference(self):
        for move in self:
            if move.state == 'done':
                move.barcode_difference = move.barcode_difference_validated
            else:
                move.barcode_difference = move._get_live_barcode_difference()
            move.barcode_above_tolerance = move._is_above_tolerance(move.barcode_difference)

    def _get_live_barcode_difference(self):
        self.ensure_one()
        if not self.product_uom_qty:
            return 0.0
        return (self.quantity - self.product_uom_qty) / self.product_uom_qty * 100

    def _is_above_tolerance(self, difference):
        self.ensure_one()
        return round(abs(difference), 2) > self.company_id.barcode_register_tolerance

    def _check_cartons_editable(self):
        if any(move.picking_id.state in ('done', 'cancel') for move in self):
            raise UserError(_("Cartons cannot be changed on a validated or cancelled operation."))

    def _sync_quantity_from_cartons(self):
        """The line quantity is the sum of its scanned cartons (still editable by hand)."""
        for move in self.filtered(lambda m: m.state not in ('done', 'cancel')):
            total = sum(move.carton_ids.mapped('quantity'))
            quantity = move.product_id.uom_id._compute_quantity(total, move.product_uom, rounding_method='HALF-UP')
            if move.product_uom.compare(quantity, move.quantity):
                move.quantity = quantity

    def action_open_cartons(self):
        self.ensure_one()
        readonly = self.picking_id.state in ('done', 'cancel')
        return {
            'type': 'ir.actions.act_window',
            'name': _("Cartons: %s", self.product_id.display_name),
            'res_model': 'stock.move.carton',
            'view_mode': 'list',
            'views': [(self.env.ref('stock_barcode_register.view_stock_move_carton_list').id, 'list')],
            'domain': [('move_id', '=', self.id)],
            'context': {
                'default_move_id': self.id,
                'create': not readonly,
                'edit': not readonly,
                'delete': not readonly,
            },
            'target': 'new',
        }
