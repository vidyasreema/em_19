{
    'name': 'The Cut Customer Emails',
    'version': '19.0.1.0.1',
    'category': 'Website/eCommerce',
    'summary': 'The Cut design for the emails of website customers (orders, account, coupons)',
    'description': """
The Cut Customer Emails
=======================

The emails of website customers get The Cut design (Annex 2, tasks 3.1 and
3.4): The Cut logo, a light card, a short text and a simple footer, without
"Powered by Odoo".

- Order confirmation, On the way, Delivered (with the next-order coupon),
  Cancelled, Your address was updated: from the "Order emails from" address.
- Welcome (account created), Choose your password (account created for the
  customer), Reset password: from no-reply@ of the email domain.
- Your coupon (coupons of website programmes).

Each email has its own template ("The Cut: ..."), editable in
Settings > Technical > Email Templates. Wholesale emails (quotations, orders
and invoices of the sales team) keep the standard design.

Website > Configuration > Settings > "The Cut design for customer emails"
switches back to the standard emails at once; uninstalling the module does too.
""",
    'author': 'Vidyasree',
    'website': 'https://thecutuae.com',
    'depends': [
        'auth_signup',
        'portal',
        'website_sale_loyalty',
        'online_orders',
    ],
    'data': [
        'data/mail_layout.xml',
        'data/mail_template_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
