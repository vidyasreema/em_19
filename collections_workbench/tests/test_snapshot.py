from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CollectionsCommon


@tagged('post_install', '-at_install')
class TestSnapshot(CollectionsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inv_sep = cls._invoice(cls.customer, 1000.0, '2026-09-15')
        cls.inv_oct = cls._invoice(cls.customer, 600.0, '2026-10-10')
        cls.inv_nov = cls._invoice(cls.customer, 300.0, '2026-11-05')   # after the period
        cls.inv_star = cls._invoice(cls.customer2, 2500.0, '2026-10-01')
        cls.inv_draft = cls._invoice(cls.customer2, 99.0, '2026-10-02', post=False)
        cls.inv_paid = cls._invoice(cls.customer2, 50.0, '2026-10-03')
        cls._pay(cls.inv_paid, 50.0, '2026-10-04')

    def _line(self, snap, partner):
        return snap.line_ids.filtered(lambda l: l.partner_id == partner)

    def test_ac2_figures_match_filter(self):
        """Before November = posted, amount due > 0, invoice date < 1/11 (AC-2)."""
        snap = self._snapshot()
        self.assertEqual(snap.state, 'active')
        moves = snap.invoice_ids.move_id
        self.assertIn(self.inv_sep, moves)
        self.assertIn(self.inv_oct, moves)
        self.assertIn(self.inv_star, moves)
        self.assertNotIn(self.inv_nov, moves, "after the period")
        self.assertNotIn(self.inv_draft, moves, "draft")
        self.assertNotIn(self.inv_paid, moves, "fully paid")
        acme = self._line(snap, self.customer)
        self.assertAlmostEqual(acme.total_due, 1600.0)
        self.assertEqual(sorted(acme.invoice_line_ids.mapped('period_key')), ['2026-09', '2026-10'])

    def test_partial_invoice_at_remaining_amount(self):
        self._pay(self.inv_sep, 400.0, '2026-10-20')
        snap = self._snapshot()
        acme = self._line(snap, self.customer)
        self.assertAlmostEqual(acme.total_due, 1200.0)

    def test_frozen_and_never_deleted(self):
        snap = self._snapshot()
        with self.assertRaises(UserError):
            snap.total_due = 1.0
        with self.assertRaises(UserError):
            self._line(snap, self.customer).total_due = 1.0
        with self.assertRaises(UserError):
            snap.unlink()

    def test_ac19_refresh_collected_snapshot_unchanged(self):
        snap = self._snapshot()
        self._pay(self.inv_oct, 600.0, '2026-11-10')
        acme = self._line(snap, self.customer)
        acme.invalidate_recordset()
        self.assertAlmostEqual(acme.live_collected, 600.0)
        self.assertEqual(acme.live_status, 'partly')
        self.assertAlmostEqual(acme.total_due, 1600.0, msg="snapshot figure unchanged")
        summary = snap._live_summary()
        self.assertAlmostEqual(summary['collected'], 600.0)
        self.assertAlmostEqual(summary['rate'], 600.0 / 4100.0)

    def test_ac3_cancelled_invoice_not_collected(self):
        snap = self._snapshot()
        self.inv_oct.button_draft()
        self.inv_oct.button_cancel()
        acme = self._line(snap, self.customer)
        inv_line = acme.invoice_line_ids.filtered(lambda i: i.move_id == self.inv_oct)
        self.assertTrue(inv_line.changed_after_snapshot)
        self.assertEqual(inv_line.collected, 0.0)
        self.assertEqual(acme.changed_invoice_count, 1)
        self.assertAlmostEqual(acme.live_collected, 0.0)

    def test_credit_note_after_snapshot_not_collected(self):
        snap = self._snapshot()
        # In a test everything shares the transaction timestamp; in real use
        # the credit note comes in a later transaction than the pull.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE collection_snapshot SET pull_date = pull_date - interval '1 hour' WHERE id = %s",
            [snap.id])
        snap.invalidate_recordset(['pull_date'])
        # full credit note, posted and matched with the invoice
        self.inv_star._reverse_moves([{'date': date(2026, 11, 8)}], cancel=True)
        self.assertEqual(self.inv_star.payment_state, 'reversed')
        star = self._line(snap, self.customer2)
        self.assertTrue(star.invoice_line_ids.changed_after_snapshot)
        self.assertAlmostEqual(star.live_collected, 0.0)

    def test_ac1_unreconciled_flag_does_not_block(self):
        self._unreconciled_payment(self.customer2, 500.0, '2026-10-30')
        wizard = self.env['collection.snapshot.wizard'].create({
            'period_type': 'before_month', 'month_date': date(2026, 11, 1)})
        self.assertGreaterEqual(wizard.unreconciled_count, 1)
        self.assertIn('Star Collections Test', wizard.unreconciled_html)
        snap = self._snapshot()
        star = self._line(snap, self.customer2)
        self.assertAlmostEqual(star.unreconciled_at_pull, 500.0)
        self.assertAlmostEqual(star.soa_balance, 2000.0)
        self.assertGreaterEqual(snap.unreconciled_customer_count, 1)

    def test_sections_by_tag(self):
        self.customer2.category_id = self.env.ref('collections_workbench.tag_court_case')
        snap = self._snapshot()
        self.assertEqual(self._line(snap, self.customer2).section, 'court')
        self.assertEqual(self._line(snap, self.customer).section, 'active')

    def test_vr1_rights(self):
        user = self.env['res.users'].create({
            'name': 'Collector', 'login': 'collector_test',
            'group_ids': [(6, 0, [self.env.ref('collections_workbench.group_collection_user').id])],
        })
        accountant = self.env['res.users'].create({
            'name': 'Accountant', 'login': 'acc_test',
            'group_ids': [(6, 0, [self.env.ref('collections_workbench.group_collection_accountant').id,
                                  self.env.ref('account.group_account_invoice').id])],
        })
        wizard = self.env['collection.snapshot.wizard'].with_user(accountant).create({
            'period_type': 'before_month', 'month_date': date(2026, 11, 1)})
        wizard.action_generate()
        snap = self.env['collection.snapshot'].search([], order='id desc', limit=1)
        with self.assertRaises(AccessError):
            self.env['collection.snapshot.wizard'].with_user(user).create({
                'period_type': 'before_month', 'month_date': date(2026, 11, 1)})
        snap._generate()
        with self.assertRaises(AccessError):
            snap.with_user(accountant).action_archive_snapshot()
        snap.action_archive_snapshot()   # admin is manager
        self.assertEqual(snap.state, 'archived')
        self.assertTrue(self.customer.exists())

    def test_duplicate_period_warning(self):
        wizard = self.env['collection.snapshot.wizard'].create({
            'period_type': 'before_month', 'month_date': date(2026, 11, 1)})
        self.assertFalse(wizard.duplicate_info)
        self._snapshot()
        wizard = self.env['collection.snapshot.wizard'].create({
            'period_type': 'before_month', 'month_date': date(2026, 11, 1)})
        self.assertIn('already exists', wizard.duplicate_info)
        with self.assertRaises(UserError):
            wizard.action_generate()
        # archiving the existing one allows a new pull
        self.env['collection.snapshot'].search([('state', '=', 'active')]).action_archive_snapshot()
        wizard = self.env['collection.snapshot.wizard'].create({
            'period_type': 'before_month', 'month_date': date(2026, 11, 1)})
        self.assertFalse(wizard.duplicate_info)

    def test_stuck_snapshot_generate_now_or_delete(self):
        """A snapshot never stays stuck in "Generating": job switched off ->
        built at once; a waiting one can be built with "Generate now" or
        deleted by the manager (never once it has customers)."""
        cron = self.env.ref('collections_workbench.ir_cron_generate_snapshot')
        cron.active = False
        wizard = self.env['collection.snapshot.wizard'].create({
            'period_type': 'before_month', 'month_date': date(2026, 11, 1)})
        result = wizard.action_generate()
        self.assertEqual(result['params']['title'], "Snapshot ready")
        snap = self.env['collection.snapshot'].search([], order='id desc', limit=1)
        self.assertEqual(snap.state, 'active')
        self.assertTrue(snap.line_ids)
        with self.assertRaises(UserError):
            snap.action_delete_unfinished()   # has customers: never deleted

        waiting = self.env['collection.snapshot'].create({
            'period_type': 'range', 'date_from': date(2026, 1, 1), 'date_to': date(2026, 10, 31)})
        accountant = self.env['res.users'].create({
            'name': 'Accountant', 'login': 'acc_stuck_test',
            'group_ids': [(6, 0, [self.env.ref('collections_workbench.group_collection_accountant').id])],
        })
        with self.assertRaises(AccessError):
            waiting.with_user(accountant).action_delete_unfinished()
        waiting.with_user(accountant).action_generate_now()
        self.assertEqual(waiting.state, 'active')
        self.assertTrue(waiting.line_ids)

        other = self.env['collection.snapshot'].create({
            'period_type': 'range', 'date_from': date(2025, 1, 1), 'date_to': date(2025, 1, 31)})
        other.action_delete_unfinished()      # admin is manager
        self.assertFalse(other.exists())
