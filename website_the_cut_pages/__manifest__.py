{
    'name': 'The Cut: Website Pages',
    'version': '19.0.1.1.0',
    'category': 'Website/Website',
    'summary': 'The Cut homepage, Delivery & Pickup, Privacy, Terms, About Us, and the header and footer of the site',
    'description': """
The Cut: Website Pages (BRD-2026-10-CONTENT-PAGES)
==================================================

- New homepage (the story from New Zealand to Abu Dhabi), Delivery & Pickup,
  Privacy Policy, Terms of Sale (at /terms) and About Us, as on the approved
  design board.
- The header and footer of every page of the site in the same design.
- Every value that can change (order cutoff, opening hours, delivery times,
  fees, free-delivery amounts, phone numbers, shop address) is read from the
  settings: delivery methods, Store Settings, the company and the website.
  A sentence whose value is empty is hidden.
- Website > Configuration > Settings > "The Cut pages" switches the design on
  or off at once.
""",
    'author': 'Vidyasree',
    'website': 'https://thecutuae.com',
    'depends': [
        'website_sale',
        'account',
        'delivery_timeslot_module',
        'website_purchase_journey',
    ],
    'data': [
        'views/res_config_settings_views.xml',
        'views/delivery_carrier_views.xml',
        'views/layout_templates.xml',
        'views/page_home.xml',
        'views/page_delivery.xml',
        'views/page_about.xml',
        'views/page_privacy.xml',
        'views/page_terms.xml',
        'data/website_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_the_cut_pages/static/src/scss/the_cut_pages.scss',
            'website_the_cut_pages/static/src/js/the_cut_pages.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
