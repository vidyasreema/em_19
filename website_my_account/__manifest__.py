{
    'name': 'Website My Account',
    'version': '19.0.1.1.2',
    'category': 'Website/Website',
    'summary': 'The Cut: app-style My Account page (profile card, orders, coupons, settings)',
    'description': """
Website My Account
==================

The My Account page (/my) of the shop in the style of shopping apps:

- profile card with the name, email, an Edit button and how complete the
  profile is (mobile number, delivery address);
- coupons ready to use, or what the customer saved;
- My Orders (last order and its status) and My Coupons;
- My Account: addresses, payment methods, favourites, tickets (no invoices);
- Settings: account details, password and sign-in, language;
- Help: WhatsApp, contact us, sign out.

Website > Configuration > Settings > "App-style My Account page" switches
back to the standard page at once; uninstalling the module does too.
""",
    'author': 'Vidyasree',
    'website': 'https://thecutuae.com',
    'depends': [
        'website_purchase_journey',
        'website_sale_wishlist',
    ],
    'data': [
        'views/res_config_settings_views.xml',
        'views/my_account_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_my_account/static/src/scss/my_account.scss',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
