from datetime import date

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestCollectionsUi(HttpCase):
    """The custom table, board and dashboard load without JS errors."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.password = 'admin'   # test transaction only, rolled back
        cls.env = cls.env(user=admin, context=dict(cls.env.context, allowed_company_ids=admin.company_id.ids))
        snap = cls.env['collection.snapshot'].create({
            'period_type': 'before_month', 'month_date': date(2026, 11, 1)})
        snap._generate()
        cls.snapshot = snap
        # give the admin some customers so "My customers" is not empty
        employee = cls.env['hr.employee'].sudo().search([('user_id', '=', admin.id)], limit=1) or \
            cls.env['hr.employee'].sudo().create({'name': 'Admin collector', 'user_id': admin.id})
        snap.line_ids[:20].partner_id.sudo().write({'collection_assignee_id': employee.id})
        snap.line_ids.partner_id._collection_recompute_status()

    def test_table(self):
        self.start_tour('/odoo/action-collections_workbench.action_collection_snapshot_line',
                        'collections_workbench_table_tour', login='admin', timeout=180)

    def test_board(self):
        self.start_tour('/odoo/action-collections_workbench.action_collection_board_collection',
                        'collections_workbench_board_tour', login='admin', timeout=180)

    def test_dashboard(self):
        self.start_tour('/odoo/action-collections_workbench.action_collection_dashboard',
                        'collections_workbench_dashboard_tour', login='admin', timeout=180)

    def test_report(self):
        self.start_tour('/odoo/action-collections_workbench.action_collection_report',
                        'collections_workbench_report_tour', login='admin', timeout=180)

    def test_bulk_assign(self):
        self.start_tour('/odoo/action-collections_workbench.action_collection_snapshot_line',
                        'collections_workbench_assign_tour', login='admin', timeout=180)
