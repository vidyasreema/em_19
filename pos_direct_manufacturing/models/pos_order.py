from odoo import fields, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    all_raw_material_ids = fields.Many2many(
        'pos.order.line.raw.material',
        string='Raw Materials Used',
        compute='_compute_all_raw_material_ids',
        help="Every raw material recorded across all order lines, "
             "aggregated for display on the order form.",
    )

    def _compute_all_raw_material_ids(self):
        for order in self:
            order.all_raw_material_ids = order.lines.mapped('raw_material_ids')

    manufacturing_order_ids = fields.One2many(
        'mrp.production',
        'pos_order_id',
        string='Manufacturing Orders',
    )
    manufacturing_order_count = fields.Integer(
        string='Manufacturing Order Count',
        compute='_compute_manufacturing_order_count',
    )

    def _compute_manufacturing_order_count(self):
        for order in self:
            order.manufacturing_order_count = len(order.manufacturing_order_ids)

    def action_view_manufacturing_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('mrp.mrp_production_action')
        action['domain'] = [('id', 'in', self.manufacturing_order_ids.ids)]
        action['context'] = {}
        return action

    def _process_saved_order(self, draft):
        result = super()._process_saved_order(draft)
        if not draft and self.state != 'cancel':
            self._create_manufacturing_orders()
            self._generate_raw_material_note()
        return result

    def _create_manufacturing_orders(self):
        self.ensure_one()
        Production = self.env['mrp.production']
        for line in self.lines:
            if not line.product_id.is_manufacture_route:
                continue
            if not line.raw_material_ids:
                continue

            move_raw_vals = [
                (0, 0, {
                    'product_id': material.product_id.id,
                    'product_uom_qty': material.qty,
                    'product_uom': material.uom_id.id,
                })
                for material in line.raw_material_ids
            ]

            Production.create({
                'product_id': line.product_id.id,
                'product_qty': line.qty,
                'product_uom_id': line.product_id.uom_id.id,
                'move_raw_ids': move_raw_vals,
                'pos_order_id': self.id,
                'origin': self.name,
                'state': 'draft',
            })

    def _generate_raw_material_note(self):
        """Builds the internal note text per BRD format:
        burger 4.5kg
        |-trimming 2.5kg
        |-brisket 2kg
        ----------------
        """
        self.ensure_one()
        blocks = []
        for line in self.lines:
            if not line.raw_material_ids:
                continue
            header = f"{line.product_id.display_name} {line.qty}{line.product_id.uom_id.name}"
            material_lines = [
                f"|-{m.product_id.display_name} {m.qty}{m.uom_id.name}"
                for m in line.raw_material_ids
            ]
            blocks.append("\n".join([header] + material_lines))

        if blocks:
            note_text = "\n----------------\n".join(blocks)
            existing_note = self.internal_note or ""
            self.internal_note = (
                f"{existing_note}\n{note_text}".strip() if existing_note else note_text
            )