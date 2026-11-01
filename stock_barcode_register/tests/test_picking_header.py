from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestPickingHeader(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('stock.group_stock_multi_locations')
        cls.stock = cls.env.ref('stock.stock_location_stock')
        cls.chiller = cls.env['stock.location'].create({'name': 'Chiller', 'location_id': cls.stock.id})
        cls.type_in = cls.env.ref('stock.picking_type_in')
        cls.type_out = cls.env.ref('stock.picking_type_out')
        cls.type_internal = cls.env.ref('stock.picking_type_internal')
        cls.type_internal.active = True
        cls.vendor = cls.env['res.partner'].create({'name': 'Global Meats'})
        cls.product = cls.env['product.product'].create({'name': 'Beef Striploin', 'is_storable': True})
        cls.employee = cls.env['hr.employee'].create({'name': 'Ali', 'stock_operation_authorized': True})
        cls.other_employee = cls.env['hr.employee'].create({'name': 'Office Clerk'})

    def _picking(self, picking_type, **vals):
        values = {
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
            'move_ids': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 10,
                'quantity': 10,
                'location_id': vals.get('location_id', picking_type.default_location_src_id.id),
                'location_dest_id': vals.get('location_dest_id', picking_type.default_location_dest_id.id),
            })],
        }
        values.update(vals)
        picking = self.env['stock.picking'].create(values)
        picking.action_confirm()
        return picking

    def test_receipt_requires_header_fields(self):
        receipt = self._picking(self.type_in, partner_id=self.vendor.id)
        with self.assertRaisesRegex(ValidationError, r"Received by.*Vendor Invoice Number"):
            receipt.button_validate()
        receipt.write({'employee_id': self.employee.id, 'vendor_invoice_ref': 'INV-1001'})
        receipt.button_validate()
        self.assertEqual(receipt.state, 'done')

    def test_internal_transfer_same_locations_rejected(self):
        self.env['stock.quant']._update_available_quantity(self.product, self.stock, 10)
        transfer = self._picking(self.type_internal, location_id=self.stock.id, location_dest_id=self.stock.id,
                                 employee_id=self.employee.id)
        with self.assertRaisesRegex(ValidationError, "must be different"):
            transfer.button_validate()
        transfer.write({'location_dest_id': self.chiller.id})
        transfer.move_ids.location_dest_id = self.chiller
        transfer.button_validate()
        self.assertEqual(transfer.state, 'done')

    def test_delivery_requires_employee(self):
        self.env['stock.quant']._update_available_quantity(self.product, self.stock, 10)
        delivery = self._picking(self.type_out)
        with self.assertRaisesRegex(ValidationError, "Delivered by"):
            delivery.button_validate()

    def test_automatic_flows_not_blocked(self):
        """POS validates with _action_done directly: no header check."""
        self.env['stock.quant']._update_available_quantity(self.product, self.stock, 10)
        delivery = self._picking(self.type_out)
        delivery.move_ids.write({'quantity': 10, 'picked': True})
        delivery._action_done()
        self.assertEqual(delivery.state, 'done')

    def test_locations_start_empty_from_menu(self):
        Picking = self.env['stock.picking']
        with Form(Picking.with_context(restricted_picking_type_code='incoming')) as receipt:
            self.assertEqual(receipt.picking_type_id, self.type_in)
            self.assertFalse(receipt.location_dest_id)
            receipt.location_dest_id = self.chiller
            receipt.partner_id = self.vendor
            self.assertEqual(receipt.location_dest_id, self.chiller, "Choosing the vendor must keep the chosen destination")
            receipt.employee_id = self.employee
            receipt.vendor_invoice_ref = 'INV-1002'

        with Form(Picking.with_context(restricted_picking_type_code='internal')) as transfer:
            self.assertFalse(transfer.location_id)
            self.assertFalse(transfer.location_dest_id)
            transfer.location_id = self.stock
            transfer.location_dest_id = self.chiller
            transfer.employee_id = self.employee

        # Without the menu context (e.g. created by code), standard defaults stay
        with Form(Picking.with_context(default_picking_type_id=self.type_in.id)) as receipt:
            self.assertEqual(receipt.location_dest_id, self.type_in.default_location_dest_id)
            receipt.partner_id = self.vendor
            receipt.employee_id = self.employee
            receipt.vendor_invoice_ref = 'INV-1003'

    def test_staff_sees_only_authorized_employees(self):
        staff = new_test_user(self.env, 'op_staff2', groups='stock_barcode_register.group_operational_staff')
        employees = self.env['hr.employee'].with_user(staff).search([('stock_operation_authorized', '=', True)])
        self.assertIn(self.employee, employees)
        self.assertNotIn(self.other_employee, employees)
