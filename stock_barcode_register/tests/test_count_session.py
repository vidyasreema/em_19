from datetime import timedelta

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import BarcodeRegisterCase


@tagged('post_install', '-at_install')
class TestCountSession(BarcodeRegisterCase):

    def _session(self, location=None):
        return self.Session.create({'location_id': (location or self.stock).id, 'employee_id': self.employee.id})

    def _count(self, session, barcode, product=None, **vals):
        line = session.line_ids.filtered(lambda l: l.product_id == (product or self.beef))
        parsed = self.env['stock.count.carton'].parse_barcode(barcode, line.product_id.id)
        return self.env['stock.count.carton'].create(dict(parsed, line_id=line.id, barcode=barcode, **vals))

    def _line(self, session, product=None):
        return session.line_ids.filtered(lambda l: l.product_id == (product or self.beef))

    def test_load_products_of_location(self):
        other = self.env['product.product'].create({'name': 'Lamb Rack', 'is_storable': True})
        negative = self.env['product.product'].create({'name': 'Mince', 'is_storable': True})
        elsewhere = self.env['product.product'].create({'name': 'Chicken', 'is_storable': True})
        Quant = self.env['stock.quant']
        Quant._update_available_quantity(other, self.stock, 5)
        Quant._update_available_quantity(negative, self.stock, -3)
        Quant._update_available_quantity(elsewhere, self.chiller, 4)
        self._receive([('C1', 12)])
        session = self._session()
        products = session.line_ids.product_id
        self.assertIn(other, products)
        self.assertIn(negative, products, "Negative balances load")
        self.assertIn(self.beef, products)
        self.assertNotIn(elsewhere, products, "Each session covers its own location only")

    def test_confirm_requires_location_and_counter(self):
        session = self.Session.create({'location_id': self.stock.id})
        with self.assertRaisesRegex(ValidationError, "Counted by"):
            session.action_confirm_quantities()
        self.assertEqual(session.state, 'draft')

    def test_baseline_and_second_count(self):
        rows = self._receive([('C1', 12), ('C2', 11), ('C3', 10)])
        c1, c2, c3 = rows.sorted('barcode')

        # Baseline: C1 and C2 counted, C3 not found -> sold without being a difference
        baseline = self._session()
        self._count(baseline, 'C1')
        self._count(baseline, 'C2')
        line = self._line(baseline)
        line.open_qty = 0.4
        self.assertEqual(line.counted_qty, 23.4)
        baseline.action_confirm_quantities()
        self.assertTrue(baseline.is_baseline)
        self.assertEqual(line.status, 'baseline')
        self.assertEqual(line.system_qty, 33)
        baseline.action_post()
        self.assertEqual(baseline.state, 'posted')
        self.assertEqual((c1 | c2).mapped('state'), ['unsold', 'unsold'])
        self.assertEqual(c3.state, 'sold')
        self.assertEqual(c3.sold_count_session_id, baseline)
        package = line.package_id
        self.assertTrue(package.barcode.startswith('CNT-') and package.barcode.endswith('-83214'))
        self.assertEqual(package.quantity, 0.4)

        quant = self.env['stock.quant'].search([('product_id', '=', self.beef.id), ('location_id', '=', self.stock.id)])
        self.assertEqual(quant.inventory_quantity, 23.4, "Posting writes the Counted column")
        self.assertEqual(quant.quantity, 33, "Posting applies nothing")
        quant.action_apply_inventory()
        self.assertTrue(baseline.apply_date)
        self.Register._cron_log_adjustments_and_scrap()
        self.assertFalse(self.Register.search([('barcode_type', '=', 'adjustment'), ('product_id', '=', self.beef.id)]),
                         "Apply after a posted session creates no ADJ")

        # Sell 11 kg (C2) through a delivery without scanning, receive C4
        with freeze_time(fields.Datetime.now() + timedelta(minutes=5)):
            delivery = self._picking(self.type_out, self.stock, self.customer, 11)
            delivery.move_ids.quantity = 11
            self._validate(delivery)
            c4 = self._receive([('C4', 9)])

        # Second count: C1 + C4 found, open package consumed, C2 out = 11 = system outflow
        with freeze_time(fields.Datetime.now() + timedelta(minutes=10)):
            second = self._session()
            self._count(second, 'C1')
            self._count(second, 'C4')
            second.action_confirm_quantities()
        line = self._line(second)
        self.assertFalse(second.is_baseline)
        self.assertEqual(second.previous_session_id, baseline)
        self.assertAlmostEqual(line.expected_qty, 12 + 11 + 0.4 + 9)
        self.assertAlmostEqual(line.matched_qty, 21)
        self.assertAlmostEqual(line.out_by_cartons, 11.4)
        self.assertAlmostEqual(line.system_outflow, 11)
        self.assertEqual(line.status, 'unexplained', "0.4 kg of the open package is not explained by the system")
        with freeze_time(fields.Datetime.now() + timedelta(minutes=15)):
            second.action_reopen()
            line.open_qty = 0.4
            second.action_confirm_quantities()
        self.assertEqual(line.status, 'matched')
        second.action_post()
        self.assertEqual(c2.state, 'sold')
        self.assertEqual(package.state, 'sold', "An open package is treated as consumed at the next count")
        self.assertEqual(c4.state, 'unsold')
        self.assertEqual(c4.last_count_session_id, second)

    def test_unrecorded_carton_and_no_basis(self):
        self.env['stock.quant']._update_available_quantity(self.beef, self.stock, 5)
        lamb = self.env['product.product'].create({'name': 'Lamb Rack', 'is_storable': True})
        self.env['stock.quant']._update_available_quantity(lamb, self.stock, 7)
        self._session().action_confirm_quantities()
        self.Session.search([('state', '=', 'compared')]).action_post()

        session = self._session()
        carton = self._count(session, 'UNKNOWN-1', quantity=6)
        self.assertFalse(carton.register_id)
        session.action_confirm_quantities()
        self.assertEqual(self._line(session).status, 'unrecorded')
        self.assertEqual(self._line(session, lamb).status, 'no_basis')
        self.assertIn("Posts as zero", self._line(session, lamb).flags)
        session.action_post()
        self.assertEqual(carton.register_id.count_session_id, session, "An unrecorded carton enters the register")

    def test_zero_stock_product_creates_inventory_line(self):
        session = self._session()
        self.env['stock.count.scan.wizard'].create({'session_id': session.id, 'product_id': self.beef.id}).action_add()
        self._count(session, 'Z1', quantity=4)
        session.action_confirm_quantities()
        self.assertFalse(self._line(session).quant_exists)
        session.action_post()
        quant = self.env['stock.quant'].search([('product_id', '=', self.beef.id), ('location_id', '=', self.stock.id)])
        self.assertEqual(quant.inventory_quantity, 4)
        self.assertEqual(quant.count_session_id, session)

    def test_add_by_scan_finds_registered_carton(self):
        row = self._receive([('C7', 12)], dest=self.chiller)
        session = self._session()
        self.assertNotIn(self.beef, session.line_ids.product_id)
        self.env['stock.count.scan.wizard'].create({'session_id': session.id, 'barcode': 'C7'}).action_add()
        line = self._line(session)
        self.assertEqual(line.carton_ids.register_id, row, "Matching is done across all locations")
        self.assertEqual(line.carton_qty, 12)

    def test_edit_counted_after_posting_logs_difference(self):
        self._receive([('C1', 12)])
        session = self._session()
        self._count(session, 'C1')
        session.action_confirm_quantities()
        session.action_post()
        quant = self.env['stock.quant'].search([('product_id', '=', self.beef.id), ('location_id', '=', self.stock.id)])
        quant.inventory_quantity = 11.5
        quant.action_apply_inventory()
        self.Register._cron_log_adjustments_and_scrap()
        adj = self.Register.search([('barcode_type', '=', 'adjustment'), ('product_id', '=', self.beef.id)])
        self.assertEqual(len(adj), 1)
        self.assertAlmostEqual(adj.quantity, -0.5, msg="ADJ for the difference only")

    def test_cancel_and_protection(self):
        session = self._session()
        self.env['stock.count.scan.wizard'].create({'session_id': session.id, 'product_id': self.beef.id}).action_add()
        self._count(session, 'X1', quantity=3)
        with self.assertRaises(UserError):
            session.unlink()
        session.action_cancel()
        self.assertEqual(session.state, 'cancel')
        self.assertTrue(session.line_ids.carton_ids, "A cancelled session keeps its scans")

    def test_duplicate_count_scan(self):
        session = self._session()
        self.env['stock.count.scan.wizard'].create({'session_id': session.id, 'product_id': self.beef.id}).action_add()
        self._count(session, 'D1', quantity=3)
        with self.assertRaisesRegex(ValidationError, "already been counted"), self.env.cr.savepoint():
            self._count(session, 'D1', quantity=3)

    def test_export(self):
        self._receive([('E1', 3)])
        session = self._session()
        self._count(session, 'E1')
        session.action_confirm_quantities()
        action = session.action_export_xlsx()
        self.assertEqual(action['type'], 'ir.actions.act_url')
