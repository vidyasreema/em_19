{
    'name': 'Website Product Feed: Meta Catalog Fields',
    'version': '19.0.1.0.0',
    'summary': 'Add the fields Meta requires (condition, description, availability, brand) to the product feed',
    'description': """
Completes the product feed (/gmc.xml) read by the Meta catalog and Google Merchant Center:

* condition: always "new".
* description: eCommerce description as text, falling back to the meta / sales
  description and finally the product name.
* availability: "out of stock" when the product has an out-of-stock ribbon
  (set on the feed, default "Out of stock" and "Sold out"), otherwise "in stock".
* brand: the value of the product's Brand attribute, as its own field.

The feed cache is reset when a product field used by the feed changes.
    """,
    'author': 'Vidyasree',
    'website': 'https://www.thecutuae.com',
    'category': 'Website/Website',
    'depends': ['website_sale_stock'],
    'data': [
        'views/gmc_templates.xml',
        'views/product_feed_views.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'license': 'LGPL-3',
    'installable': True,
}
