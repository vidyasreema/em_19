import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


class StockZeroQuantWizard(models.TransientModel):
    _name = 'stock.zero.quant.wizard'
    _description = 'Zero-Stock Products in Physical Inventory'

    location_ids = fields.Many2many(
        'stock.location',
        string='Locations',
        domain=[('usage', '=', 'internal')],
        required=True,
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_locations(self):
        """Selected internal locations plus their internal children."""
        return self.env['stock.location'].search([
            ('id', 'child_of', self.location_ids.ids),
            ('usage', '=', 'internal'),
        ])

    def _get_kit_products(self):
        """Products that are kits (Manufacturing BoM of type Kit).
        Kits hold no stock of their own and Odoo refuses to create quants
        for them, so they must be skipped."""
        kits = self.env['product.product']
        if 'mrp.bom' not in self.env:
            return kits
        boms = self.env['mrp.bom'].sudo().with_context(active_test=False).search([
            ('type', '=', 'phantom'),
        ])
        for bom in boms:
            kits |= bom.product_id or bom.product_tmpl_id.product_variant_ids
        return kits

    def _get_products(self):
        """Phase 1 scope: goods with Track Inventory on, no lot/serial
        tracking, and not a kit."""
        products = self.env['product.product'].search([
            ('is_storable', '=', True),
            ('tracking', '=', 'none'),
        ])
        return products - self._get_kit_products()

    def _quant_model(self):
        # inventory_mode=False -> plain ORM create, so the custom flag is allowed.
        return self.env['stock.quant'].sudo().with_context(inventory_mode=False)

    def _open_physical_inventory(self):
        return self.env['stock.quant'].action_view_inventory()

    # ------------------------------------------------------------------
    # Option ON
    # ------------------------------------------------------------------
    def action_show(self):
        self.ensure_one()
        Quant = self._quant_model()
        product_ids = self._get_products().ids
        vals_list = []
        for location in self._get_locations():
            # Any existing quant (positive, negative or zero) counts as
            # "already has a line" -> this is what prevents duplicates.
            existing = set(Quant.search([
                ('location_id', '=', location.id),
                ('product_id', 'in', product_ids),
            ]).product_id.ids)
            for product_id in product_ids:
                if product_id in existing:
                    continue
                vals_list.append({
                    'product_id': product_id,
                    'location_id': location.id,
                    'quantity': 0,
                    'inventory_quantity': 0,
                    'inventory_quantity_set': True,
                    # Assigned user keeps the line out of the standard
                    # zero-quant cleanup (verify in Odoo 19 source).
                    'user_id': self.env.user.id,
                    'zero_option_line': True,
                })
        for i in range(0, len(vals_list), BATCH_SIZE):
            Quant.create(vals_list[i:i + BATCH_SIZE])
        _logger.info('Zero-stock option ON: created %s lines', len(vals_list))
        return self._open_physical_inventory()

    # ------------------------------------------------------------------
    # Option OFF
    # ------------------------------------------------------------------
    def action_hide(self):
        self.ensure_one()
        Quant = self._quant_model()
        # Only our own lines that nobody has touched (still zero everywhere).
        lines = Quant.search([
            ('zero_option_line', '=', True),
            ('location_id', 'in', self._get_locations().ids),
            ('quantity', '=', 0),
            ('reserved_quantity', '=', 0),
            ('inventory_quantity', '=', 0),
        ])
        count = len(lines)
        lines.unlink()
        _logger.info('Zero-stock option OFF: removed %s lines', count)
        return self._open_physical_inventory()