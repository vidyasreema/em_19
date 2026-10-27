{
    'name': 'Website Purchase Journey',
    'version': '19.0.1.5.3',
    'category': 'Website/eCommerce',
    'summary': 'The Cut purchase journey: add from the shop, weight choice, location on entry',
    'description': """
        Website Purchase Journey (Annex 3, Version 2)
        =============================================

        Part 1 - Shop:
        - Add button on the product card, disabled by the Out of stock ribbon
          (the same ribbons as the product feed)
        - "Choose weight" sheet for products with several weights (variants),
          with the price of each weight; "from" price and "In cart" on the card
        - Location on entry (browser permission), "Deliver to" bar with the
          delivery promise; the location starts the first address

        Part 2 - Single order page (cart, coupon, summary, sign-up box, guest
        checkout with email, consent, driver instructions, receiver, address,
        payment) instead of Cart > Address > Payment. Coupons apply to the
        amount above the free-delivery threshold once delivery is free.
        The welcome coupon is given at sign-up.

        Part 3 - After the order: guests create their account in one tap from
        the confirmation page; tracking bar in the shop for the open order
        (status from the Online Orders stages); Track / Order details page and
        Order again in My orders.

        Website > Configuration > Settings > "New purchase journey" switches it off.
    """,
    'author': 'Vidyasree',
    'website': 'https://thecutuae.com',
    'depends': [
        'website_sale',
        'website_sale_meta_feed',
        'delivery_timeslot_module',
        'website_delivery_geolocation',
        'website_sale_loyalty',
        'auth_oauth',
        'online_orders',
        'website_sale_wishlist',
    ],
    'data': [
        'data/loyalty_data.xml',
        'views/res_config_settings_views.xml',
        'views/shop_templates.xml',
        'views/location_templates.xml',
        'views/order_templates.xml',
        'views/portal_templates.xml',
        'views/after_order_templates.xml',
        'views/track_templates.xml',
        'views/account_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_purchase_journey/static/src/scss/journey.scss',
            'website_purchase_journey/static/src/interactions/*.js',
        ],
        'web.assets_tests': [
            'website_purchase_journey/static/tests/tours/*',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
