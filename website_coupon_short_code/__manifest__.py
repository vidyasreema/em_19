{
    'name': 'Website Coupon Short Code',
    'version': '19.0.1.0.0',
    'category': 'Website/Website',
    'summary': 'The Cut: one short code per coupon programme (SECOND10) instead of the long coupon codes',
    'description': """
Website Coupon Short Code
=========================

Odoo gives each personal coupon (welcome, next order) its own long code, such as
044b-a7ac-4985. With this module a coupon programme can have one short
"Code shown to customers" (SECOND10, WELCOME10):

- the customers see that code instead of the long one: My coupons, the
  coupons of the order page, the "You earned a coupon" message, the order
  totals and the Delivered email;
- a signed-in customer who types it gets their own coupon of the programme
  (the one that expires first); someone without that coupon gets "You don't
  have this coupon". The code gives no discount by itself.

The long codes stay in Odoo (backend, "Apply to my order"). An empty field
keeps the long code. Uninstalling the module brings the long codes back.
""",
    'author': 'Vidyasree',
    'website': 'https://thecutuae.com',
    'depends': [
        'website_purchase_journey',
        'online_orders',
    ],
    'data': [
        'views/loyalty_program_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
