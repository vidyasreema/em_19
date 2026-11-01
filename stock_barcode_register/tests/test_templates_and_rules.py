from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import new_test_user

from .common import BarcodeRegisterCase


@tagged('post_install', '-at_install')
class TestTemplatesAndRules(BarcodeRegisterCase):

    # ------------------------------------------------------------------
    # Reading templates
    # ------------------------------------------------------------------

    def test_firstlight_template(self):
        parsed = self.Carton.parse_barcode('28321410136230103824', self.beef.id)
        self.assertEqual(parsed['barcode_type'], 'template')
        self.assertAlmostEqual(parsed['quantity'], 10.136)
        self.assertEqual(parsed['carton_number'], '230103824')
        self.assertEqual(parsed['product_code'], '83214')
        self.assertFalse(parsed['pack_date'], "Pack date is requested")

        receipt = self._receipt(10.136)
        carton = self._scan(receipt.move_ids, '28321410136230103824')
        self.assertTrue(carton.pack_date_estimated)
        self._validate(receipt)
        self.assertEqual(carton.register_id.template_id, self.env.ref('stock_barcode_register.template_firstlight'))

    def test_label_weight_keeps_three_decimals(self):
        """Cartons and the register keep the label weight; only the line total rounds."""
        self.env.ref('uom.decimal_product_uom').digits = 2
        receipt = self._receipt(20.011)
        cartons = self._scan(receipt.move_ids, '28321410136230103824')
        cartons |= self._scan(receipt.move_ids, '28321409875230103825')
        self.assertEqual(cartons.mapped('quantity'), [10.136, 9.875])
        self.assertAlmostEqual(receipt.move_ids.quantity, 20.01)
        self.assertFalse(receipt.move_ids.barcode_difference)
        self._validate(receipt)
        self.assertEqual(cartons.register_id.mapped('quantity'), [10.136, 9.875])

    def test_template_unit_product_quantity_typed(self):
        unit_product = self.env['product.product'].create({'name': 'Burger Pack', 'is_storable': True})
        parsed = self.Carton.parse_barcode('28321410136230103824', unit_product.id)
        self.assertEqual(parsed['barcode_type'], 'template')
        self.assertFalse(parsed['quantity'])

    def test_template_test_field_and_approval(self):
        template = self.env['stock.barcode.template'].create({
            'name': 'Progressive', 'length': 16, 'prefix': '91',
            'qty_start': 3, 'qty_length': 5, 'qty_decimals': 2, 'carton_start': 8, 'carton_length': 0,
            'pack_date_start': 0,
        })
        template.test_barcode = '9101234000000123'
        self.assertIn('12.34', template.test_result)
        template.test_barcode = '123'
        self.assertIn('No match', template.test_result)
        self.assertFalse(self.Carton.parse_barcode('9101234000000123', self.beef.id)['barcode_type'] == 'template',
                         "A draft template does not read barcodes")

        template.sample_ids = [(0, 0, {'barcode': '9101234000000123'})]
        with self.assertRaisesRegex(ValidationError, "at least two labels"):
            template.action_approve()
        template.sample_ids = [(0, 0, {'barcode': '9101234000000124'})]
        with self.assertRaisesRegex(ValidationError, "different quantities"):
            template.action_approve()
        template.sample_ids = [(0, 0, {'barcode': '9100999000000125'})]
        template.action_approve()
        self.assertEqual(template.state, 'approved')
        self.assertEqual(self.Carton.parse_barcode('9101234000000123', self.beef.id)['barcode_type'], 'template')

    def test_template_overlap_rejected(self):
        with self.assertRaisesRegex(ValidationError, "would read the same barcodes"):
            self.env['stock.barcode.template'].create({'name': 'Copy', 'length': 20, 'prefix': '28'})

    # ------------------------------------------------------------------
    # Vendor scan requirement
    # ------------------------------------------------------------------

    def test_vendor_scan_required(self):
        self.vendor.barcode_scan_requirement = 'required'
        receipt = self._receipt(10)
        receipt.move_ids.quantity = 10
        with self.assertRaisesRegex(ValidationError, "requires carton details"):
            self._validate(receipt)
        # A carton without a barcode passes with a generated barcode
        self.Carton.create({'move_id': receipt.move_ids.id, 'quantity': 10})
        self._validate(receipt)
        self.assertEqual(receipt.state, 'done')

    def test_vendor_scan_warning(self):
        self.vendor.barcode_scan_requirement = 'warning'
        receipt = self._receipt(10)
        receipt.move_ids.quantity = 10
        self._validate(receipt)
        self.assertEqual(receipt.state, 'done')
        self.assertIn('without carton details', receipt.message_ids[0].body)

    def test_vendor_hint(self):
        self.vendor.barcode_expected_type = 'gs1'
        receipt = self._receipt(10)
        self.assertEqual(receipt.vendor_barcode_hint, 'gs1')

    # ------------------------------------------------------------------
    # Delivery follow-up
    # ------------------------------------------------------------------

    def test_delivery_without_sales_document_creates_activity(self):
        self.env['stock.quant']._update_available_quantity(self.beef, self.stock, 10)
        delivery = self._picking(self.type_out, self.stock, self.customer, 5)
        delivery.move_ids.quantity = 5
        self._validate(delivery)
        self.assertEqual(delivery.activity_ids.user_id, self.followup_user)
        self.assertIn('sales document', delivery.activity_ids.summary)

    # ------------------------------------------------------------------
    # Daily job
    # ------------------------------------------------------------------

    def test_daily_job_logs_adjustment_and_scrap(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'stock_barcode_register.start_date', fields.Datetime.to_string(fields.Datetime.now() - timedelta(days=1)))
        quant = self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': self.beef.id, 'location_id': self.stock.id, 'inventory_quantity': 20,
        })
        quant.action_apply_inventory()
        scrap = self.env['stock.scrap'].create({
            'product_id': self.beef.id, 'scrap_qty': 1.5, 'location_id': self.stock.id,
        })
        scrap.action_validate()

        self.Register._cron_log_adjustments_and_scrap()
        adj = self.Register.search([('barcode_type', '=', 'adjustment'), ('product_id', '=', self.beef.id)])
        scr = self.Register.search([('barcode_type', '=', 'scrap'), ('product_id', '=', self.beef.id)])
        self.assertEqual(adj.quantity, 20)
        self.assertTrue(adj.barcode.startswith('ADJ-') and adj.barcode.endswith('-83214'))
        self.assertEqual(adj.location_id, self.stock)
        self.assertEqual(scr.quantity, -1.5)
        self.assertEqual(scr.scrap_id, scrap)
        self.assertTrue(scr.barcode.startswith('SCR-'))

        self.Register._cron_log_adjustments_and_scrap()
        self.assertEqual(self.Register.search_count([('barcode_type', 'in', ('adjustment', 'scrap'))]), 2, "Logged once")

    def test_daily_job_ignores_before_start_date(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'stock_barcode_register.start_date', fields.Datetime.to_string(fields.Datetime.now() + timedelta(days=1)))
        self.env['stock.quant']._update_available_quantity(self.beef, self.stock, 3)
        quant = self.env['stock.quant'].search([('product_id', '=', self.beef.id), ('location_id', '=', self.stock.id)])
        quant.with_context(inventory_mode=True).inventory_quantity = 5
        quant.action_apply_inventory()
        self.Register._cron_log_adjustments_and_scrap()
        self.assertFalse(self.Register.search([('barcode_type', '=', 'adjustment')]))

    # ------------------------------------------------------------------
    # New product from receipt
    # ------------------------------------------------------------------

    def test_create_product_from_receipt(self):
        officer = new_test_user(self.env, 'pricing_officer', groups='stock_barcode_register.group_barcode_product_creator')
        staff = new_test_user(self.env, 'staff_no_create', groups='stock_barcode_register.group_operational_staff')
        receipt = self._receipt(10)
        categ = self.env.ref('product.product_category_goods', raise_if_not_found=False) or self.env['product.category'].search([], limit=1)
        Wizard = self.env['stock.barcode.product.wizard']
        vals = {'picking_id': receipt.id, 'name': 'Venison Loin', 'uom_id': self.kg.id, 'categ_id': categ.id,
                'storage_type': 'frozen', 'standard_price': 42.5, 'product_uom_qty': 8}
        with self.assertRaises(AccessError):
            Wizard.with_user(staff).create(vals)

        wizard = Wizard.with_user(officer).create(dict(vals, name='Beef Striploin'))
        self.assertIn(self.beef, wizard.duplicate_ids)
        with self.assertRaisesRegex(UserError, "Possible duplicates"):
            wizard.action_create()

        wizard = Wizard.with_user(officer).create(vals)
        self.assertFalse(wizard.duplicate_ids)
        wizard.action_create()
        product = receipt.move_ids.product_id.filtered(lambda p: p.name == 'Venison Loin')
        self.assertTrue(product)
        self.assertEqual(product.storage_type, 'frozen')
        self.assertEqual(product.standard_price, 42.5)
        self.assertTrue(product.product_tmpl_id.activity_ids, "A review Activity is created")
        if 'available_in_pos' in product._fields:
            self.assertTrue(product.available_in_pos)

    # ------------------------------------------------------------------
    # Export and cartons button
    # ------------------------------------------------------------------

    def test_receipt_export_and_cartons_button(self):
        receipt = self._receipt(12)
        self._scan(receipt.move_ids, 'EXP-1', quantity=12)
        self.assertEqual(receipt.scanned_carton_count, 1)
        self.assertEqual(receipt.action_open_scanned_cartons()['domain'], [('picking_id', '=', receipt.id)])
        self._validate(receipt)
        action = receipt.action_export_cartons_xlsx()
        self.assertEqual(action['type'], 'ir.actions.act_url')
