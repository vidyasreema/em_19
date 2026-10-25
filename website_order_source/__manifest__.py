{
    'name': 'Website Order Source',
    'version': '19.0.1.0.0',
    'category': 'Website/eCommerce',
    'summary': 'The Cut: "How did you hear about us?" after the order, kept on the order',
    'description': """
Website Order Source
====================

After placing an order, the confirmation page asks the customer
"How did you hear about us? One tap is enough." (Instagram, Facebook,
A friend...).

- The answer is saved on the order (field "Heard About Us") and written
  in its history (chatter), by the customer.
- Answered once on the website (then only the answer is shown); the sales
  team can change it on the order (tracked in the history).
- Online Orders > Reporting > Orders by Source: orders and amounts by answer.
- Online Orders > Configuration > Order Sources: the answers shown (order,
  names, archive).

Website > Configuration > Settings > "Ask how customers heard about us"
switches the question off at once; uninstalling the module does too.
""",
    'author': 'Vidyasree',
    'website': 'https://thecutuae.com',
    'depends': [
        'website_purchase_journey',
        'online_orders',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/order_source_data.xml',
        'views/order_source_views.xml',
        'views/sale_order_views.xml',
        'views/res_config_settings_views.xml',
        'views/confirmation_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
