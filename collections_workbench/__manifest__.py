{
    'name': 'Collections Workbench',
    'version': '19.0.3.2.0',
    'category': 'Accounting/Accounting',
    'summary': 'Monthly collection cycle inside Odoo: frozen snapshot, '
               'follow-up notes, pipelines, approvals and collection report',
    'description': """
Collections Workbench
=====================
Replaces the monthly Excel export + AI comparison with a workflow inside Odoo
(BRD Collections Workbench v1.1):

* Frozen snapshot of posted customer invoices with a remaining balance
* Time-stamped, non-editable follow-up notes (promises, visits, no answer...)
* Configurable follow-up pipelines and stages, with VIP approvals
* Reconciliation block: no email or statement while a payment is unreconciled
* Live comparison of collected amounts against the frozen snapshot
""",
    'depends': [
        'account',
        'contacts',
        'hr',
        'mail',
        'sales_commission',  # res.partner.sales_man (hr.employee)
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/partner_category_data.xml',
        'data/note_category_data.xml',
        'data/pipeline_data.xml',
        'data/ir_cron_data.xml',
        'data/mail_template_data.xml',
        'data/followup_data.xml',
        'wizard/collection_snapshot_wizard_views.xml',
        'wizard/collection_followup_wizard_views.xml',
        'wizard/collection_assign_wizard_views.xml',
        'report/collection_reports.xml',
        'views/collection_snapshot_views.xml',
        'views/collection_note_views.xml',
        'views/collection_pipeline_views.xml',
        'views/collection_approval_views.xml',
        'views/collection_cycle_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/collection_output_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'collections_workbench/static/src/**/*',
        ],
        'web.assets_tests': [
            'collections_workbench/static/tests/tours/*.js',
        ],
    },
    'post_init_hook': '_post_init_hook',
    'author': 'Vidyasree',
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
}
