from odoo import fields, models, api


class PosOrderLineRawMaterial(models.Model):
    _name = 'pos.order.line.raw.material'
    _inherit = ['pos.load.mixin']
    _description = 'Raw Material Selected for a POS Manufactured Order Line'

    order_line_id = fields.Many2one(
        'pos.order.line',
        string='POS Order Line',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Raw Material',
        required=True,
        help="Any product in the catalog can be selected as a raw "
             "material — searchable, no restriction.",
    )
    qty = fields.Float(
        string='Quantity Used',
        required=True,
        default=0.0,
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='product_id.uom_id',
        store=True,
        readonly=True,
    )
    manufactured_product_id = fields.Many2one(
        'product.product',
        string='Manufactured Item',
        related='order_line_id.product_id',
        store=True,
        readonly=True,
        help="The manufactured product this raw material was used for, "
             "shown for backend readability only.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'order_line_id', 'product_id', 'qty', 'uom_id', 'write_date']

    @api.model
    def _load_pos_data_domain(self, data, config):
        return [('id', 'in', [])]