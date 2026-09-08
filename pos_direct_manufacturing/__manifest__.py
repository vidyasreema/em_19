{
    'name': 'POS Direct Manufacturing Integration',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Create Manufacturing Orders directly from POS for '
               'meat-shop style ad-hoc raw material usage',
    'description': """
        Links POS sales of manufactured products (e.g. burgers) to
        auto-created draft Manufacturing Orders, with raw materials
        selected manually per order line at the point of sale —
        no fixed BOM, since recipes vary per order.
    """,
    'depends': [
        'point_of_sale',
        'mrp',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_config_views.xml',
        'views/pos_order_views.xml',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml'
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_direct_manufacturing/static/src/js/order_line_patch.js',
            'pos_direct_manufacturing/static/src/xml/order_line_patch.xml',
            'pos_direct_manufacturing/static/src/js/raw_material_popup.js',
            'pos_direct_manufacturing/static/src/xml/raw_material_popup.xml',
            'pos_direct_manufacturing/static/src/js/data_service_options_patch.js',
            'pos_direct_manufacturing/static/src/js/pos_order_patch.js',
            'pos_direct_manufacturing/static/src/js/pos_store_patch.js'
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}