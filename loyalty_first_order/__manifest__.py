{
    'name': 'Loyalty: First Order Only',
    'version': '19.0.1.4.0',
    'summary': 'Restrict promotions to a customer\'s first confirmed order',
    'depends': ['sale_loyalty', 'website_sale_loyalty'],
    'data': [
        'views/loyalty_program_views.xml',
        'views/website_sale_templates.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
}
