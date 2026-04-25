# -*- coding: utf-8 -*-
{
    'name': 'Website Delivery Timeslot',
    'version': '19.0.2.0.0',
    'category': 'Website/eCommerce',
    'summary': 'Smart delivery timing messages based on store working hours',
    'description': """
        Website Delivery Time Slot Management
        ======================================

        Displays intelligent delivery messages to customers based on when they order:

        Scenario 1 - Within working hours:
            No message shown. Order proceeds normally.

        Scenario 2 - Shortly after closing (within 1-2 hrs of close):
            "Your order will be ready for delivery tomorrow during working hours"

        Scenario 3 - Late off-hours (after midnight / deep night before opening):
            "Your order will be available for delivery today by [opening time]"
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
        'views/store_settings.xml'
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
}
