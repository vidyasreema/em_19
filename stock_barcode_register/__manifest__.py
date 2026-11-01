{
    'name': 'Barcode Register',
    'version': '19.0.1.1.0',
    'category': 'Inventory/Inventory',
    'summary': 'Carton-level barcode register for receipts, transfers, deliveries and counts',
    'description': """
Barcode Register
================
Historical register of product cartons (barcode, quantity, pack date) filled at
receipt, internal transfer, delivery and count. It is for comparison and audit
only: it never creates a stock move or changes a balance or valuation.

Also adds an operational app for warehouse staff showing only Receipts,
Internal Transfers and Count.
    """,
    'author': 'Vidyasree',
    'website': 'https://www.thecutuae.com',
    'depends': ['stock', 'hr', 'barcodes_gs1_nomenclature'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'data/register_start_data.xml',
        'data/stock_barcode_template_data.xml',
        'views/stock_barcode_register_views.xml',
        'views/product_template_views.xml',
        'views/operational_app_menus.xml',
        'views/hr_employee_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_move_carton_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'views/stock_barcode_template_views.xml',
        'views/stock_count_session_views.xml',
        'wizard/product_wizard_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'stock_barcode_register/static/src/**/*',
        ],
        'web.assets_tests': [
            'stock_barcode_register/static/tests/tours/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
