# -*- coding: utf-8 -*-
{
    'name': 'POS Orderline Price Detail',
    'version': '19.0.1.0.0',
    'summary': 'Shows qty × unit price under product name in POS order lines (like Odoo 18)',
    'category': 'Point of Sale',
    'author': 'Vidyasree',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_orderline_price_detail/static/src/overrides/orderline_price_detail.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
