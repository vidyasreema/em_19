{
    'name': 'POS Pack Selection',
    'version': '19.0.1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Select product pack sizes (carton, half carton) from the POS',
    'author': 'Vidyasree',
    'depends': ['point_of_sale'],
    'data': ['views/product_pricelist_item_views.xml',
             'views/pack_price_views.xml',
             'views/product_template_views.xml',
             'views/pos_order_views.xml'],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_pack_selection/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}