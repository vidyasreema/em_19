{
    'name': 'Zero-Stock Products in Physical Inventory',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Create countable lines for zero-stock products in Physical Inventory',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/zero_quant_wizard_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
