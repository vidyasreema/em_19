from odoo import fields
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools.barcode import get_barcode_check_digit


def gs1_barcode(weight_cg, pack_date, carton_number, gtin_base='0941234567890'):
    gtin = gtin_base + str(get_barcode_check_digit('0000' + gtin_base + '0'))
    return f"01{gtin}3102{weight_cg:06d}13{pack_date}21{carton_number}"


class BarcodeRegisterCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('stock.group_stock_multi_locations')
        cls.company = cls.env.company
        cls.followup_user = new_test_user(cls.env, 'followup_common', groups='stock.group_stock_user')
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
        cls.Carton = cls.env['stock.move.carton']
        cls.Register = cls.env['stock.barcode.register']
        cls.Session = cls.env['stock.count.session']
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

    def _receipt(self, qty, product=None, dest=None, partner=None):
        return self._picking(self.type_in, self.supplier, dest or self.stock, qty, product,
                             partner_id=(partner or self.vendor).id, vendor_invoice_ref='INV-1001')

    def _scan(self, move, barcode, **vals):
        parsed = self.Carton.parse_barcode(barcode, move.product_id.id)
        values = dict(parsed, move_id=move.id, barcode=barcode)
        values.update(vals)
        return self.Carton.create(values)

    def _validate(self, picking):
        return picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids).button_validate()

    def _receive(self, cartons, dest=None):
        """Receive (barcode, qty) cartons of beef and return their register rows."""
        receipt = self._receipt(sum(qty for _barcode, qty in cartons), dest=dest)
        for barcode, qty in cartons:
            self._scan(receipt.move_ids, barcode, quantity=qty)
        self._validate(receipt)
        return receipt.move_ids.carton_ids.register_id
