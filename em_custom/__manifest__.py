# -*- coding: utf-8 -*-
{
    'name': 'EM Custom',
    'version': '19.0.1.0.0',
    'category': 'Customizations',
    'summary': 'Small custom changes and enhancements for EM project.',
    'description': """
        EM Custom Module
        ================
        This module contains small custom changes specific to the EM project, including:
        - Unreconciled customer payment activity scheduler
    """,
    'author': 'Vidyasree',
    'website': 'https://www.thecutuae.com',
    'depends': [
        'base',
        'account',
        'sale_management',
        'mail',
    ],
    'data': [
        'views/unreconciled_activity_cron.xml',
        'views/sale_order_inherit.xml'
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}