# -*- coding: utf-8 -*-
{
    'name': 'Sales Commission System',
    'version': '1.0.0',
    'category': 'Sales/Commission',
    'summary': 'Automated sales commission based on net profit and collections',
    'description': """
        Sales Commission Management
        ============================

        Complete commission system with:
        * Customer-to-salesperson assignment
        * Net profit calculation
        * Collection tracking (fully paid invoices only)
        * Monthly targets and statements
        * Automated commission payout workflow
        * Comprehensive reporting and audit trail
    """,

    'author': 'Vidyasree',
    'website': 'https://thecutuae.com',

    'depends': [
        'base',
        'hr',
        'account',
        'sale_management',
        'contacts',
    ],

    'data': [
        "security/ir.model.access.csv",
        "views/res_partner_inherit.xml",
        "views/hr_employee_inherit.xml",
        "views/commission_config_views.xml",
        "views/commission_target_views.xml",
        "views/commission_statement_views.xml",
        "reports/commission_report.xml",
        "views/account_move_inherit.xml",
        "views/backfill_commission_sales_man.xml"

    ],
    'assets': {
        'web.assets_backend': [
            'sales_commission/static/src/css/commission_dashboard.css',
            'sales_commission/static/src/xml/commission_dashboard.xml',
            'sales_commission/static/src/js/commission_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}