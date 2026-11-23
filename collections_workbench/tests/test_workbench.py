import base64
import io
import zipfile
from datetime import date

from odoo.tests import tagged

from .common import CollectionsCommon


@tagged('post_install', '-at_install')
class TestWorkbench(CollectionsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer.email = 'acme@example.com'
        for amount, day in [(100.0, '2025-06-10'), (200.0, '2026-02-10'), (300.0, '2026-05-10'),
                            (400.0, '2026-09-10'), (500.0, '2026-10-10')]:
            cls._invoice(cls.customer, amount, day)
        cls.inv_star = cls._invoice(cls.customer2, 1000.0, '2026-10-01')
        cls.Line = cls.env['collection.snapshot.line']

    def _data(self, snap, domain=None, mode='default'):
        return self.Line.workbench_data(snap.id, domain or [], mode)

    def test_ac6_default_periods(self):
        snap = self._snapshot()
        data = self._data(snap)
        self.assertEqual([p['label'] for p in data['periods']], ['2025', 'Jan–Aug 2026', 'Sep 2026', 'Oct 2026'])
        acme = next(r for r in data['rows'] if r['partner_id'] == self.customer.id)
        self.assertEqual(acme['periods'], {'2025': 100.0, 'merged': 500.0, '2026-09': 400.0, '2026-10': 500.0})
        months = self._data(snap, mode='month')['periods']
        self.assertEqual(len(months), 5)
        self.assertEqual(len(self._data(snap, mode='year')['periods']), 2)

    def test_header_filters_and_predefined(self):
        snap = self._snapshot()
        self._unreconciled_payment(self.customer2, 50.0, '2026-11-02')
        rows = self._data(snap, [('unreconciled_now', '>', 0)])['rows']
        self.assertEqual([r['partner_id'] for r in rows], [self.customer2.id])
        self.env['collection.note'].create({'partner_id': self.customer.id,
                                            'category_id': self.cat_no_answer.id})
        rows = self._data(snap, [('latest_note_category_id', 'in', [self.cat_no_answer.id])])['rows']
        self.assertEqual([r['partner_id'] for r in rows], [self.customer.id])
        self.assertEqual(len(self._data(snap, [('live_status', 'in', ['none'])])['rows']), 2)
        self.assertEqual(len(self._data(snap, [('total_due', '>=', 1200)])['rows']), 1)

    def test_prefs_per_user(self):
        Pref = self.env['collection.workbench.pref']
        self.assertEqual(Pref.get_prefs(), {})
        Pref.set_prefs({'widths': {'partner': 300}, 'hidden': ['salesman']})
        Pref.set_prefs({'widths': {'partner': 320}, 'hidden': []})
        self.assertEqual(Pref.get_prefs()['widths']['partner'], 320)
        self.assertEqual(Pref.search_count([('user_id', '=', self.env.uid)]), 1)

    def test_excel_export(self):
        snap = self._snapshot()
        url = self.Line.workbench_export(snap.id, [], 'default', None)
        attachment = self.env['ir.attachment'].browse(int(url.split('/')[3].split('?')[0]))
        content = base64.b64decode(attachment.datas)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(content)), "xlsx is a zip")

    def test_reports_render(self):
        snap = self._snapshot()
        html = self.env['ir.actions.report']._render_qweb_html(
            'collections_workbench.report_monthly', snap.ids)[0].decode()
        self.assertIn('Net total', html)
        self.assertIn('Rate per assignee', html)
        html = self.env['ir.actions.report']._render_qweb_html(
            'collections_workbench.report_statement', self.customer.ids, data={'mode': 'statement'})[0].decode()
        self.assertIn('Statement of account', html)
        html = self.env['ir.actions.report']._render_qweb_html(
            'collections_workbench.report_statement', self.customer.ids, data={'mode': 'ledger'})[0].decode()
        self.assertIn('Customer ledger', html)

    def test_statement_package_excludes_unreconciled(self):
        snap = self._snapshot()
        self._unreconciled_payment(self.customer2, 50.0, '2026-11-02')
        pack = self.env['collection.statement.package'].create({'snapshot_id': snap.id})
        pack._build()
        self.assertEqual(pack.state, 'done')
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(pack.attachment_id.datas))) as archive:
            names = archive.namelist()
        self.assertIn('ACME Collections Test.pdf', names)
        self.assertNotIn('Star Collections Test.pdf', names)
        self.assertIn('Star Collections Test', pack.excluded)
        self.assertTrue(any(n.endswith('.xlsx') for n in names))

    def test_statement_package_without_background_job(self):
        """Job switched off (test copy): the user is told, and "Build now" builds it."""
        snap = self._snapshot()
        self.env.ref('collections_workbench.ir_cron_statement_package').active = False
        result = self.env['collection.package.wizard'].create({'snapshot_id': snap.id}).action_build()
        self.assertEqual(result['params']['type'], 'warning')
        self.assertIn('Build now', result['params']['message'])
        waiting = self.env['collection.statement.package'].search([], order='id desc', limit=1)
        self.assertEqual(waiting.state, 'queued')
        waiting.action_build_now()
        self.assertEqual(waiting.state, 'done')
        self.assertTrue(waiting.attachment_id)

    def test_assignment_notifies_and_discussion_is_internal(self):
        snap = self._snapshot()
        line = snap.line_ids.filtered(lambda l: l.partner_id == self.customer)
        employee = self.env['hr.employee'].sudo().create({'name': 'Collector Emp', 'user_id': self.env.user.id})
        self.Line.workbench_set_assignee(line.id, employee.id)
        self.assertEqual(self.customer.collection_assignee_id, employee)
        msg = line.message_ids.filtered(lambda m: 'assigned to Collector Emp' in (m.body or ''))
        self.assertIn(self.env.user.partner_id, msg.partner_ids)
        # the customer is never notified from the internal discussion (BR-23)
        posted = line.message_post(body='internal', partner_ids=[self.customer.id, self.env.user.partner_id.id])
        self.assertNotIn(self.customer, posted.partner_ids)

    def test_dashboard_and_board_tabs(self):
        snap = self._snapshot()
        self.customer._collection_recompute_status()
        data = self.Line.dashboard_data('team')
        # a manager opens on the team view by default, like the simulation
        self.assertEqual(self.Line.dashboard_data()['scope'], 'team')
        send = next(c for c in data['cards'] if c['key'] == 'send')
        self.assertGreaterEqual(send['value'], 1)
        tabs = self.env['collection.pipeline'].board_tabs()
        collection = next(t for t in tabs if t.get('pipeline_id') == self.env.ref(
            'collections_workbench.pipeline_collection').id)
        self.assertGreaterEqual(collection['count'], 2, "snapshot customers not followed up yet")
        self.assertEqual(tabs[0]['key'], 'approvals')
        keys = {c['key'] for c in data['cards']}
        self.assertTrue({'late_us', 'blacklist', 'close', 'thanks', 'activities'} <= keys)
        self.assertEqual(next(c for c in data['cards'] if c['key'] == 'activities')['filter'], 'open_activities')

    def test_report_page_data(self):
        snap = self._snapshot()
        data = self.env['collection.snapshot'].report_page_data(snap.id)
        self.assertEqual(data['snapshot_id'], snap.id)
        self.assertEqual([r['label'] for r in data['summary']],
                         ['Total', 'Blacklist', 'Court case', 'Agreements', 'Net total'])
        total = data['summary'][0]
        self.assertAlmostEqual(total['share'], 1.0)
        self.assertEqual(total['paid'] + total['partly'] + total['not_paid'], total['count'])
        self.assertIn('rate_net', data['live'])
        self.assertIn('avg_days', data['live'])
        html = self.env['ir.actions.report']._render_qweb_html(
            'collections_workbench.report_monthly', snap.ids)[0].decode()
        self.assertIn('Avg days to close', html)
        self.assertIn('Share', html)

    def test_panel_and_note_from_followup(self):
        snap = self._snapshot()
        line = snap.line_ids.filtered(lambda l: l.partner_id == self.customer)
        wiz = self.env['collection.followup.wizard'].with_context(
            default_partner_ids=self.customer.ids, default_kind='note').create({
                'note_category_id': self.cat_promise.id, 'note_promise_date': date(2026, 12, 20),
                'note_amount': 500.0, 'note': 'Will pay half'})
        wiz.action_confirm()
        panel = self.Line.workbench_panel(line.id)
        self.assertEqual(panel['notes'][0]['category'], 'Promise to pay')
        self.assertEqual(panel['notes'][0]['amount'], 500.0)
        self.assertAlmostEqual(panel['balance'], 1500.0)

    def test_fr6_custom_grouping(self):
        snap = self._snapshot()
        data = self.Line.workbench_data(snap.id, [], 'custom', ['2026-05', '2026-10'])
        self.assertEqual([p['label'] for p in data['periods']], ['Jun 2025–Feb 2026', 'May–Sep 2026', 'Oct 2026'])
        acme = next(r for r in data['rows'] if r['partner_id'] == self.customer.id)
        self.assertEqual(acme['periods'], {'c0': 300.0, 'c1': 700.0, 'c2': 500.0})
        self.assertEqual(len(data['all_months']), 5)

    def test_collector_without_accounting_rights(self):
        """A Collections user with no Accounting group can do the daily work (AC-28)."""
        collector = self.env['res.users'].create({
            'name': 'Pure Collector', 'login': 'pure_collector', 'email': 'pure@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('collections_workbench.group_collection_user').id])],
        })
        self.assertFalse(collector.has_group('account.group_account_invoice'))
        snap = self._snapshot()
        self._unreconciled_payment(self.customer2, 50.0, '2026-11-02')
        employee = self.env['hr.employee'].sudo().create({'name': 'Pure Collector', 'user_id': collector.id})
        line = snap.line_ids.filtered(lambda l: l.partner_id == self.customer)
        self.Line.workbench_set_assignee(line.id, employee.id)
        Line = self.Line.with_user(collector)
        data = Line.workbench_data(snap.id, [], 'default')
        self.assertEqual(len(data['rows']), 2)
        self.assertTrue(Line.dashboard_data('mine')['cards'])
        self.assertEqual(Line.dashboard_data()['scope'], 'mine')  # collectors: only their customers
        self.assertTrue(Line.workbench_panel(line.id))
        star = snap.line_ids.filtered(lambda l: l.partner_id == self.customer2).with_user(collector)
        self.assertGreater(star.unreconciled_now, 0)
        self.assertIn(star.credit_state, ('none', 'hold', 'available'))
        self.env['collection.note'].with_user(collector).create({
            'partner_id': self.customer.id, 'category_id': self.cat_promise.id,
            'promise_date': date(2026, 12, 20), 'amount': 100.0})
        self.env['collection.followup.wizard'].with_user(collector).with_context(
            default_partner_ids=self.customer.ids).create({
                'stage_id': self.env.ref('collections_workbench.stage_claim').id}).action_confirm()
        self.assertEqual(self.customer.collection_stage_id, self.env.ref('collections_workbench.stage_claim'))
        self.assertTrue(line.with_user(collector).pay_check is not None)

    def test_statement_package_same_customer_names(self):
        twin = self.env['res.partner'].create({'name': 'ACME Collections Test'})
        self._invoice(twin, 70.0, '2026-10-05')
        snap = self._snapshot()
        pack = self.env['collection.statement.package'].create({'snapshot_id': snap.id})
        pack._build()
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(pack.attachment_id.datas))) as archive:
            names = archive.namelist()
        pdfs = [n for n in names if n.startswith('ACME Collections Test')]
        self.assertEqual(len(pdfs), 2, names)
        self.assertEqual(len(set(names)), len(names))
