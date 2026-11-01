from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from ..models.res_company import _followup_user_domain


@tagged('post_install', '-at_install')
class TestBarcodeRegister(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({'name': 'Beef Striploin', 'is_storable': True})
        cls.Register = cls.env['stock.barcode.register']

    def test_product_unsold_carton_stats(self):
        self.Register.create([
            {'barcode': 'C1', 'product_id': self.product.id, 'quantity': 11.75},
            {'barcode': 'C2', 'product_id': self.product.id, 'quantity': 12.0},
            {'barcode': 'C3', 'product_id': self.product.id, 'quantity': 10.0, 'state': 'sold'},
        ])
        tmpl = self.product.product_tmpl_id
        self.assertEqual(tmpl.barcode_register_count, 2)
        self.assertAlmostEqual(tmpl.barcode_register_qty, 23.75)
        action = tmpl.action_open_barcode_register()
        self.assertEqual(action['domain'], [('product_tmpl_id', '=', tmpl.id)])

    def test_past_alert_filter(self):
        today = fields.Date.context_today(self.Register)
        past = self.Register.create({'barcode': 'P', 'product_id': self.product.id, 'alert_date': today - timedelta(days=1)})
        future = self.Register.create({'barcode': 'F', 'product_id': self.product.id, 'alert_date': today + timedelta(days=1)})
        no_date = self.Register.create({'barcode': 'N', 'product_id': self.product.id})
        records = past | future | no_date
        self.assertEqual(records.filtered_domain([('is_past_alert', '=', True)]), past)
        self.assertEqual(records.filtered_domain([('is_past_alert', '=', False)]), future | no_date)
        self.assertEqual(self.Register.search([('id', 'in', records.ids), ('is_past_alert', '=', True)]), past)
        self.assertEqual(self.Register.search([('id', 'in', records.ids), ('is_past_alert', '!=', True)]), future | no_date)

    def test_operational_staff_menus(self):
        Menu = self.env['ir.ui.menu']
        stock_root = self.env.ref('stock.menu_stock_root')
        op_root = self.env.ref('stock_barcode_register.menu_operational_root')

        staff = new_test_user(self.env, 'op_staff', groups='stock_barcode_register.group_operational_staff')
        visible = Menu.with_user(staff)._visible_menu_ids()
        self.assertIn(op_root.id, visible)
        self.assertIn(self.env.ref('stock_barcode_register.menu_operational_receipts').id, visible)
        self.assertNotIn(stock_root.id, visible, "Operational staff must not see the Inventory app")

        office = new_test_user(self.env, 'office_user', groups='stock.group_stock_user')
        visible = Menu.with_user(office)._visible_menu_ids()
        self.assertIn(stock_root.id, visible)
        self.assertNotIn(op_root.id, visible)

        admin = new_test_user(self.env, 'stock_admin', groups='stock.group_stock_manager,stock_barcode_register.group_operational_staff')
        visible = Menu.with_user(admin)._visible_menu_ids()
        self.assertIn(stock_root.id, visible)
        self.assertIn(op_root.id, visible)

    def test_followup_users_are_internal_stock_users(self):
        portal = new_test_user(self.env, 'portal_followup', groups='base.group_portal')
        office = new_test_user(self.env, 'office_followup', groups='stock.group_stock_user')
        sales_only = new_test_user(self.env, 'sales_followup', groups='base.group_user')
        field_info = self.env['res.config.settings'].fields_get(['barcode_register_followup_user_ids'])
        domain = field_info['barcode_register_followup_user_ids']['domain']
        self.assertIn('share', str(domain), "The settings dropdown is filtered")
        allowed = self.env['res.users'].search(_followup_user_domain(self.env['res.company']))
        self.assertIn(office, allowed)
        self.assertNotIn(portal, allowed)
        self.assertNotIn(sales_only, allowed)
