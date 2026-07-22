{
    'name': 'POS Payment Link In',
    'version': '19.0.1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Record incoming money that has no order behind it',
    'author': 'Vidyasree',
    'depends': ['point_of_sale'],
    'data': ['views/res_config_settings.xml',
             'views/pos_session_view.xml'],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_payment_link_in/static/src/app/*.js',
            'pos_payment_link_in/static/src/app/*.xml',
        ],
    },
    'license': 'LGPL-3',
}