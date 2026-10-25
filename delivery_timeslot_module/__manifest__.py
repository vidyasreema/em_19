# -*- coding: utf-8 -*-
{
    'name': 'Website Delivery Timeslot',
    'version': '19.0.3.2.0',
    'category': 'Website/eCommerce',
    'summary': 'Smart delivery timing messages based on store working hours',
    'description': """
        Website Delivery Promise
        ========================

        Tells the customer when the order will arrive, based on the delivery
        method and the time the order is placed (Annex 3, section 8):

        Scenario 1 - Same day: before the method's last same-day order time.
        Scenario 2 - Next working day: after it, or for methods without same day.
        Scenario 3 - Before opening: later the same day.

        The promise (type, message, promised time) is saved on the order when
        the customer pays, and the Delivery Date is set to the promised time.
    """,
    'author': 'Vidyasree',
    'depends': [
        'base',
        'sale',
        'delivery',
        'website_sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/delivery_carrier_inherit.xml',
        'views/website_sale_delivery_templates.xml',
        'views/sale_order_report_inherit.xml',
        'views/sale_order_view_inherit.xml',
        'views/store_settings.xml',
        'views/website_sale_confirmation.xml',
        'data/mail_template_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'delivery_timeslot_module/static/src/js/checkout_delivery_timing.js',
            'delivery_timeslot_module/static/src/css/custom_delivery_banner.css'
            # 'delivery_timeslot_module/static/src/js/checkout_delivery_confirm.js'
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
