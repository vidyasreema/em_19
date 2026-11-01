from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestBarcodeRegisterUi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref('base.user_admin').group_ids |= cls.env.ref('stock.group_stock_multi_locations')
        cls.stock = cls.env.ref('stock.stock_location_stock')
        cls.employee = cls.env['hr.employee'].create({'name': 'Ali', 'stock_operation_authorized': True})
        cls.beef = cls.env['product.product'].create({
            'name': 'Beef Striploin', 'default_code': '83214', 'is_storable': True,
            'uom_id': cls.env.ref('uom.product_uom_kgm').id,
        })

    def test_receipt_scan_window(self):
        receipt = self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_in').id,
            'partner_id': self.env['res.partner'].create({'name': 'Global Meats'}).id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock.id,
            'employee_id': self.employee.id,
            'vendor_invoice_ref': 'INV-1',
            'move_ids': [(0, 0, {'product_id': self.beef.id, 'product_uom_qty': 24})],
        })
        receipt.action_confirm()
        url = f'/odoo/action-stock_barcode_register.action_operational_receipts/{receipt.id}'
        self.start_tour(url, 'stock_barcode_register_receipt_scan', login='admin', timeout=120)
        move = receipt.move_ids
        self.assertEqual(len(move.carton_ids), 3)
        self.assertAlmostEqual(move.quantity, 25.75)
        self.assertEqual(set(move.carton_ids.mapped('barcode_type')), {'gs1', 'manual', 'generated'})
        self.assertTrue(move.carton_ids.filtered(lambda c: c.barcode_type == 'generated').barcode.startswith('REC-'))

    def test_count_scan_window(self):
        self.env['stock.barcode.register'].create({
            'barcode': 'C-REG-1', 'product_id': self.beef.id, 'quantity': 12.5, 'location_id': self.stock.id,
        })
        session = self.env['stock.count.session'].create({'location_id': self.stock.id, 'employee_id': self.employee.id})
        url = f'/odoo/action-stock_barcode_register.action_stock_count_session/{session.id}'
        self.start_tour(url, 'stock_barcode_register_count_scan', login='admin', timeout=120)
        carton = session.line_ids.carton_ids
        self.assertEqual(carton.quantity, 12.5)
        self.assertTrue(carton.register_id)
