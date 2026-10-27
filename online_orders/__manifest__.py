{
    'name': 'Online Orders',
    'version': '19.0.1.1.0',
    'category': 'Sales/Sales',
    'summary': 'Sales team board for website orders: stages, dispatch page, customer addresses',
    'description': """
        Online Orders (Annex 4)
        =======================

        Manage website orders from the moment they are placed until delivery:

        - Board by stage (configurable stage records, like CRM stages)
        - Order page with everything needed to dispatch through Careem,
          with copy buttons
        - Customer card with the delivery addresses (child addresses)
        - Stage emails (email template on the stage) and activities
        - Delivery quality report (Pivot / Graph)
        - Access groups: Sales, Marketing, Management

        The standard order state does not change, except on cancellation.
    """,
    'author': 'Vidyasree',
    'website': 'https://thecutuae.com',
    'depends': [
        'sale_stock',
        'sale_loyalty',
        'website_sale',
        'contacts',
        'delivery_timeslot_module',
        'website_delivery_geolocation',
    ],
    'data': [
        'security/online_orders_security.xml',
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
        'data/online_order_stage_data.xml',
        'data/ir_cron_data.xml',
        'wizard/online_order_cancel_wizard_views.xml',
        'views/online_order_stage_views.xml',
        'views/sale_order_views.xml',
        'views/res_partner_views.xml',
        'views/report_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'online_orders/static/src/kanban/*',
        ],
        'web.assets_tests': [
            'online_orders/static/tests/tours/*',
        ],
    },
    'post_init_hook': '_online_orders_post_init',
    'uninstall_hook': '_online_orders_uninstall',
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
