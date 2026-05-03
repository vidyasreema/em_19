{
    'name': 'Customer Performance Analysis Report',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Custom PDF report for customer performance analysis (migrated from Studio v18)',
    'author': 'Custom',
    'depends': ['base', 'account', 'sale'],
    'data': [
        'report/customer_performance_template.xml',
        'views/report_action.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
