from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

GS1_KEYS = ('01', '13', '21')


class StockMoveCarton(models.Model):
    """A carton scanned on an operation line. Saved as a draft inside the operation;
    it only reaches the barcode register when the operation is validated."""
    _name = 'stock.move.carton'
    _description = 'Scanned Carton'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    move_id = fields.Many2one('stock.move', 'Operation Line', required=True, index=True, ondelete='cascade')
    picking_id = fields.Many2one(related='move_id.picking_id', store=True, index=True)
    picking_type_code = fields.Selection(related='move_id.picking_id.picking_type_code')
    product_id = fields.Many2one(related='move_id.product_id', store=True)
    product_uom_id = fields.Many2one(related='move_id.product_id.uom_id', string='Unit')
    company_id = fields.Many2one(related='move_id.company_id', store=True)
    state = fields.Selection(related='move_id.picking_id.state', string='Operation Status')

    barcode = fields.Char('Barcode', help="Leave empty at receipt to generate a REC barcode.")
    carton_number = fields.Char('Carton Number')
    product_code = fields.Char('Product Code', help="Product code read from the barcode (GS1 AI 01).")
    barcode_type = fields.Selection([
        ('gs1', 'GS1'),
        ('template', 'Template'),
        ('manual', 'Manual'),
        ('fixed', 'Fixed'),
        ('generated', 'Generated (REC)'),
    ], string='Type', required=True, default='manual')
    template_id = fields.Many2one('stock.barcode.template', 'Reading Template', readonly=True)
    # 3 decimals: keep the exact label weight (e.g. 10.136 kg) even when stock quantities round to 2
    quantity = fields.Float('Quantity', digits=(16, 3), help="Quantity in the product unit, as on the label.")
    carton_count = fields.Integer('Cartons', default=1)
    pack_date = fields.Date('Pack Date')
    pack_date_estimated = fields.Boolean('Estimated', readonly=True)
    alert_date = fields.Date('Alert Date')
    alert_date_manual = fields.Boolean('Manually Edited', readonly=True)
    register_id = fields.Many2one('stock.barcode.register', 'Register Row', readonly=True, index='btree_not_null', ondelete='set null')

    @api.constrains('barcode', 'carton_number', 'barcode_type', 'move_id')
    def _check_unique_in_document(self):
        for carton in self:
            if not carton.barcode:
                raise ValidationError(_("A carton must have a barcode."))
            domain = [('picking_id', '=', carton.picking_id.id), ('id', '!=', carton.id)]
            if carton.carton_number:
                domain += ['|', ('barcode', '=', carton.barcode),
                           '&', ('carton_number', '=', carton.carton_number), ('product_id', '=', carton.product_id.id)]
            else:
                domain += [('barcode', '=', carton.barcode)]
            if carton.picking_id and self.search_count(domain, limit=1):
                raise ValidationError(_("Barcode %s has already been scanned in this document.", carton.barcode))

    @api.constrains('quantity', 'carton_count')
    def _check_quantity(self):
        for carton in self:
            if carton.quantity < 0 or carton.carton_count < 1:
                raise ValidationError(_("Carton quantity cannot be negative and the carton count must be at least 1."))

    # ------------------------------------------------------------------
    # Barcode reading
    # ------------------------------------------------------------------

    @api.model
    def parse_barcode(self, barcode, product_id):
        """Read a scanned barcode in order: standard GS1, reading templates, manual.

        :return: dict with barcode_type, quantity (False when it must be typed),
                 pack_date, carton_number, product_code
        """
        product = self.env['product.product'].browse(product_id)
        barcode = (barcode or '').strip()
        return (
            self._parse_gs1(barcode, product)
            or self._parse_template(barcode, product)
            or {'barcode_type': 'manual', 'quantity': False, 'pack_date': False, 'carton_number': False,
                'product_code': False, 'template_id': False}
        )

    def _get_gs1_nomenclature(self):
        nomenclature = self.env.company.nomenclature_id
        if not nomenclature.is_gs1_nomenclature:
            nomenclature = self.env.ref('barcodes_gs1_nomenclature.default_gs1_nomenclature', raise_if_not_found=False)
        return nomenclature

    def _parse_gs1(self, barcode, product):
        nomenclature = self._get_gs1_nomenclature()
        if not nomenclature or not barcode:
            return False
        try:
            parts = nomenclature.gs1_decompose_extended(barcode)
        except ValidationError:
            return False
        if not parts:
            return False
        by_ai = {part['ai']: part for part in parts}
        weight = next((part for ai, part in by_ai.items() if ai.startswith('310')), None)
        if not weight and not any(ai in by_ai for ai in GS1_KEYS):
            return False
        quantity = False
        # Weight is read only for products defined in a weight unit; a product by unit has its quantity typed
        kg = self.env.ref('uom.product_uom_kgm')
        if weight and product and product.uom_id._has_common_reference(kg):
            quantity = kg._compute_quantity(weight['value'], product.uom_id, round=False)
        return {
            'barcode_type': 'gs1',
            'quantity': quantity,
            'pack_date': by_ai['13']['value'] if '13' in by_ai else False,
            'carton_number': by_ai['21']['value'] if '21' in by_ai else False,
            'product_code': by_ai['01']['value'] if '01' in by_ai else False,
            'template_id': False,
        }

    def _parse_template(self, barcode, product):
        """Defined reading templates (Firstlight...)."""
        result = self.env['stock.barcode.template']._read_barcode(barcode)
        if not result:
            return False
        template = self.env['stock.barcode.template'].browse(result['template_id'])
        quantity = result['quantity']
        # The template quantity is in its own unit (kg); a product by unit has its quantity typed
        if quantity and product and template.qty_uom_id and product.uom_id._has_common_reference(template.qty_uom_id):
            result['quantity'] = template.qty_uom_id._compute_quantity(quantity, product.uom_id, round=False)
        else:
            result['quantity'] = False
        return result

    # ------------------------------------------------------------------
    # Dates
    # ------------------------------------------------------------------

    def _get_receipt_date(self):
        picking = self.picking_id
        return fields.Date.context_today(self, picking.date_done) if picking.date_done else fields.Date.context_today(self)

    def _get_computed_alert_date(self, pack_date):
        if not pack_date:
            return False
        days = self.product_id.product_tmpl_id._get_barcode_alert_days(self.company_id or self.env.company)
        return pack_date + timedelta(days=days) if days else False

    def _get_date_updates(self, vals):
        """Pack date: barcode, else typed, else receipt date flagged Estimated (receipts only).
        Alert date: pack date + alert age, flagged when edited by hand."""
        self.ensure_one()
        updates = {}
        pack_date = self.pack_date
        if 'pack_date' in vals or not pack_date:
            if pack_date:
                updates['pack_date_estimated'] = False
            elif self.picking_type_code == 'incoming':
                pack_date = self._get_receipt_date()
                updates.update(pack_date=pack_date, pack_date_estimated=True)
        computed = self._get_computed_alert_date(pack_date)
        if vals.get('alert_date'):
            updates['alert_date_manual'] = self.alert_date != computed
        elif not self.alert_date_manual or 'alert_date' in vals:
            updates.update(alert_date=computed, alert_date_manual=False)
        return updates

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def _get_generated_barcode(self, product, date=None):
        ref = product.default_code or str(product.id)
        date = (date or fields.Date.context_today(self)).strftime('%Y%m%d')
        seq = self.env['ir.sequence'].next_by_code('stock.barcode.register.generated')
        return f"REC-{ref}-{date}-{seq}"

    def _match_register(self):
        """Transfers and deliveries: find the carton in the register."""
        self.ensure_one()
        if self.barcode_type == 'fixed':
            return self.env['stock.barcode.register']
        domain = [('product_id', '=', self.product_id.id), ('state', '=', 'unsold')]
        if self.carton_number:
            domain += [('carton_number', '=', self.carton_number)]
        else:
            domain += [('barcode', '=', self.barcode)]
        return self.env['stock.barcode.register'].search(domain, order='date desc, id desc', limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        moves = self.env['stock.move'].browse([vals['move_id'] for vals in vals_list if vals.get('move_id')])
        moves._check_cartons_editable()
        for vals in vals_list:
            if not vals.get('barcode'):
                move = self.env['stock.move'].browse(vals.get('move_id'))
                if move.picking_code != 'incoming':
                    raise UserError(_("A carton without a barcode can only be added at receipt."))
                vals['barcode'] = self._get_generated_barcode(move.product_id)
                vals['barcode_type'] = 'generated'
        cartons = super().create(vals_list)
        for carton, vals in zip(cartons, vals_list):
            updates = {}
            register = carton._match_register() if carton.picking_type_code in ('internal', 'outgoing') else False
            if register:
                updates['register_id'] = register.id
                if not vals.get('quantity'):
                    updates.update(quantity=register.quantity, carton_count=register.carton_count)
            if register and not vals.get('pack_date'):
                updates.update(
                    pack_date=register.pack_date, pack_date_estimated=register.pack_date_estimated,
                    alert_date=register.alert_date, alert_date_manual=register.alert_date_manual,
                )
            else:
                updates.update(carton._get_date_updates(vals))
            if updates:
                carton._system_write(updates)
        cartons.move_id._sync_quantity_from_cartons()
        return cartons

    def _system_write(self, vals):
        return self.with_context(barcode_register_system=True, barcode_register_skip_dates=True).write(vals)

    def write(self, vals):
        if not self.env.context.get('barcode_register_system'):
            self.move_id._check_cartons_editable()
        res = super().write(vals)
        if {'pack_date', 'alert_date'} & vals.keys() and not self.env.context.get('barcode_register_skip_dates'):
            for carton in self:
                if updates := carton._get_date_updates(vals):
                    carton._system_write(updates)
        if {'quantity', 'move_id'} & vals.keys():
            self.move_id._sync_quantity_from_cartons()
        return res

    def unlink(self):
        moves = self.move_id
        moves._check_cartons_editable()
        res = super().unlink()
        moves.exists()._sync_quantity_from_cartons()
        return res
