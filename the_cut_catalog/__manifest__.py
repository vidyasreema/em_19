# -*- coding: utf-8 -*-
{
    'name': 'The Cut Catalog',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Build and export custom product catalogs as PDF from inventory.',
    'description': """
        The Cut Catalog
        ===============
        This module allows building a designed product catalog from inventory products,
        editing presentation and pricing per catalog without touching source product data,
        and exporting it as an archived PDF with its own ID and date.
    """,
    'author': 'Vidyasree',
    'website': 'https://www.thecutuae.com',
    'depends': [
        'base',
        'product',
        'sale_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/catalog_config.xml',
        'views/catalog_builder.xml',
        'report/catalog_report.xml',
        'report/catalog_report_template.xml',
        'views/product_category.xml'

    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}