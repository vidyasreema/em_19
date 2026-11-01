from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools.barcode import get_barcode_check_digit


def gs1_barcode(weight_cg, pack_date, carton_number, gtin_base='0941234567890'):
    gtin = gtin_base + str(get_barcode_check_digit('0000' + gtin_base + '0'))
    return f"01{gtin}3102{weight_cg:06d}13{pack_date}21{carton_number}"


@tagged('post_install', '-at_install')
class TestCartons(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('stock.group_stock_multi_locations')
        cls.company = cls.env.company
        cls.followup_user = new_test_user(cls.env, 'followup', groups='stock.group_stock_user')
        cls.company.write({
            'barcode_register_tolerance': 0.5,
            'barcode_alert_days_chilled': 80,
            'barcode_register_followup_user_ids': [(6, 0, cls.followup_user.ids)],
        })
        cls.stock = cls.env.ref('stock.stock_location_stock')
        cls.chiller = cls.env['stock.location'].create({'name': 'Chiller', 'location_id': cls.stock.id})
        cls.supplier = cls.env.ref('stock.stock_location_suppliers')
        cls.customer = cls.env.ref('stock.stock_location_customers')
        cls.type_in = cls.env.ref('stock.picking_type_in')
        cls.type_out = cls.env.ref('stock.picking_type_out')
        cls.type_internal = cls.env.ref('stock.picking_type_internal')
        cls.type_internal.active = True
        cls.vendor = cls.env['res.partner'].create({'name': 'Global Meats'})
        cls.employee = cls.env['hr.employee'].create({'name': 'Ali', 'stock_operation_authorized': True})
        cls.kg = cls.env.ref('uom.product_uom_kgm')
        cls.beef = cls.env['product.product'].create({
            'name': 'Beef Striploin', 'default_code': '83214', 'is_storable': True,
            'uom_id': cls.kg.id, 'storage_type': 'chilled',
        })
        cls.pack = cls.env['product.product'].create({'name': 'Burger Pack', 'is_storable': True})
        cls.Carton = cls.env['stock.move.carton']
        cls.Register = cls.env['stock.barcode.register']
        cls.today = fields.Date.context_today(cls.Carton)

    def _picking(self, picking_type, src, dest, qty, product=None, **vals):
        product = product or self.beef
        picking = self.env['stock.picking'].create(dict({
            'picking_type_id': picking_type.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'employee_id': self.employee.id,
            'move_ids': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'location_id': src.id,
                'location_dest_id': dest.id,
            })],
        }, **vals))
        picking.action_confirm()
        return picking

    def _receipt(self, qty, product=None):
        return self._picking(self.type_in, self.supplier, self.stock, qty, product,
                             partner_id=self.vendor.id, vendor_invoice_ref='INV-1001')

    def _scan(self, move, barcode, **vals):
        parsed = self.Carton.parse_barcode(barcode, move.product_id.id)
        values = dict(parsed, move_id=move.id, barcode=barcode)
        values.update(vals)
        return self.Carton.create(values)

    def _validate(self, picking):
        return picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids).button_validate()

    # ------------------------------------------------------------------
    # Barcode reading
    # ------------------------------------------------------------------

    def test_parse_gs1(self):
        parsed = self.Carton.parse_barcode(gs1_barcode(1175, '261001', '230103824'), self.beef.id)
        self.assertEqual(parsed['barcode_type'], 'gs1')
        self.assertAlmostEqual(parsed['quantity'], 11.75)
        self.assertEqual(parsed['pack_date'], date(2026, 10, 1))
        self.assertEqual(parsed['carton_number'], '230103824')
        self.assertTrue(parsed['product_code'])

    def test_parse_gs1_unit_product_quantity_typed(self):
        parsed = self.Carton.parse_barcode(gs1_barcode(1175, '261001', 'X1'), self.pack.id)
        self.assertEqual(parsed['barcode_type'], 'gs1')
        self.assertFalse(parsed['quantity'], "Weight is read only for products defined in a weight unit")

    def test_parse_manual(self):
        parsed = self.Carton.parse_barcode('1512021', self.beef.id)
        self.assertEqual(parsed['barcode_type'], 'manual')
        self.assertFalse(parsed['quantity'])

    # ------------------------------------------------------------------
    # Receipt
    # ------------------------------------------------------------------

    def test_receipt_scan_and_validate(self):
        receipt = self._receipt(24)
        move = receipt.move_ids
        gs1 = self._scan(move, gs1_barcode(1175, '261001', 'C1'))
        manual = self._scan(move, 'AGRA-0001', quantity=12.0)

        self.assertEqual(gs1.pack_date, date(2026, 10, 1))
        self.assertFalse(gs1.pack_date_estimated)
        self.assertEqual(gs1.alert_date, date(2026, 10, 1) + timedelta(days=80))
        self.assertEqual(manual.pack_date, self.today, "Missing pack date uses the receipt date")
        self.assertTrue(manual.pack_date_estimated)
        self.assertAlmostEqual(move.quantity, 23.75, msg="Line quantity is the sum of the cartons")
        self.assertEqual(move.carton_count, 2)

        with self.assertRaisesRegex(ValidationError, "already been scanned"), self.env.cr.savepoint():
            self._scan(move, 'AGRA-0001', quantity=12.0)
        self.assertEqual(len(move.carton_ids), 2)

        # -1.04% is above the 0.5% tolerance: a note is required
        with self.assertRaisesRegex(ValidationError, "note is required"):
            self._validate(receipt)
        move.barcode_note = "Vendor short, credit note requested"
        self._validate(receipt)
        self.assertEqual(receipt.state, 'done')

        rows = self.Register.search([('picking_id', '=', receipt.id)])
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows.mapped('barcode_type')), {'gs1', 'manual'})
        self.assertEqual(rows.mapped('vendor_invoice_ref'), ['INV-1001', 'INV-1001'])
        self.assertEqual(rows.location_id, self.stock)
        self.assertEqual(gs1.register_id.carton_number, 'C1')
        self.assertAlmostEqual(move.barcode_difference, -1.04, places=2)

        activity = receipt.activity_ids
        self.assertEqual(activity.user_id, self.followup_user)
        self.assertIn('INV-1001', activity.note)

        with self.assertRaises(UserError):
            gs1.quantity = 5
        with self.assertRaises(UserError):
            receipt.unlink()

    def test_receipt_within_tolerance_no_note(self):
        receipt = self._receipt(12)
        self._scan(receipt.move_ids, 'AGRA-0002', quantity=11.95)  # -0.42%
        self._validate(receipt)
        self.assertEqual(receipt.state, 'done')
        self.assertFalse(receipt.activity_ids)

    def test_receipt_manual_line_gets_generated_barcode(self):
        receipt = self._receipt(10)
        receipt.move_ids.quantity = 10
        self._validate(receipt)
        row = self.Register.search([('picking_id', '=', receipt.id)])
        self.assertEqual(len(row), 1)
        self.assertEqual(row.barcode_type, 'generated')
        self.assertTrue(row.barcode.startswith('REC-83214-%s-' % self.today.strftime('%Y%m%d')))
        self.assertEqual(row.quantity, 10)
        self.assertTrue(row.pack_date_estimated)
        self.assertEqual(row.alert_date, self.today + timedelta(days=80))

    def test_receipt_remainder_without_scan_gets_generated_barcode(self):
        receipt = self._receipt(8)
        self._scan(receipt.move_ids, 'AGRA-0003', quantity=5)
        receipt.move_ids.quantity = 8
        self._validate(receipt)
        rows = self.Register.search([('picking_id', '=', receipt.id)])
        self.assertEqual(sorted(rows.mapped('quantity')), [3, 5])

    def test_carton_without_barcode_at_receipt(self):
        receipt = self._receipt(5)
        carton = self.Carton.create({'move_id': receipt.move_ids.id, 'quantity': 5})
        self.assertEqual(carton.barcode_type, 'generated')
        self.assertTrue(carton.barcode.startswith('REC-'))

    def test_fixed_barcode(self):
        receipt = self._receipt(60)
        carton = self._scan(receipt.move_ids, '1512021', barcode_type='fixed', quantity=60, carton_count=5)
        self.assertEqual(receipt.move_ids.carton_count, 5)
        with self.assertRaisesRegex(ValidationError, "already been scanned"), self.env.cr.savepoint():
            self._scan(receipt.move_ids, '1512021', barcode_type='fixed', quantity=12)
        self._validate(receipt)
        self.assertEqual(carton.register_id.carton_count, 5)

    def test_alert_date_manual_edit(self):
        receipt = self._receipt(12)
        carton = self._scan(receipt.move_ids, 'AGRA-0004', quantity=12, pack_date=date(2026, 9, 1))
        self.assertEqual(carton.alert_date, date(2026, 9, 1) + timedelta(days=80))
        self.assertFalse(carton.alert_date_manual)
        carton.alert_date = date(2026, 10, 15)
        self.assertTrue(carton.alert_date_manual)
        carton.pack_date = date(2026, 9, 5)
        self.assertEqual(carton.alert_date, date(2026, 10, 15), "A manual alert date is kept")
        self.assertFalse(carton.pack_date_estimated)

    # ------------------------------------------------------------------
    # Transfer and delivery
    # ------------------------------------------------------------------

    def _received_carton(self):
        receipt = self._receipt(11.75)
        barcode = gs1_barcode(1175, '261001', 'C9')
        self._scan(receipt.move_ids, barcode)
        self._validate(receipt)
        return barcode, receipt.move_ids.carton_ids.register_id

    def test_internal_transfer_updates_location(self):
        barcode, row = self._received_carton()
        transfer = self._picking(self.type_internal, self.stock, self.chiller, 11.75)
        carton = self.Carton.create({'move_id': transfer.move_ids.id, 'barcode': barcode, 'carton_number': 'C9'})
        self.assertEqual(carton.register_id, row)
        self.assertEqual(carton.quantity, 11.75, "Quantity comes from the register")
        self.assertEqual(carton.pack_date, date(2026, 10, 1))
        self._validate(transfer)
        self.assertEqual(row.location_id, self.chiller)
        self.assertEqual(row.state, 'unsold')
        self.assertFalse(self.Register.search_count([('picking_id', '=', transfer.id)]), "No new row from a transfer")

    def test_delivery_marks_sold(self):
        barcode, row = self._received_carton()
        delivery = self._picking(self.type_out, self.stock, self.customer, 11.75)
        self._scan(delivery.move_ids, barcode)
        self._validate(delivery)
        self.assertEqual(row.state, 'sold')
        self.assertEqual(row.sale_ref, delivery.name)
        self.assertEqual(row.sale_picking_id, delivery)

    def test_delivery_manual_no_generated_barcode(self):
        self.env['stock.quant']._update_available_quantity(self.beef, self.stock, 10)
        delivery = self._picking(self.type_out, self.stock, self.customer, 10)
        with self.assertRaises(UserError):
            self.Carton.create({'move_id': delivery.move_ids.id, 'quantity': 1})
        delivery.move_ids.quantity = 10
        self._validate(delivery)
        self.assertEqual(delivery.state, 'done')
        self.assertFalse(self.Register.search_count([('product_id', '=', self.beef.id)]))
