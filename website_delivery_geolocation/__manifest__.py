{
    "name": "Website Delivery Geolocation",
    "version": "19.0.1.0.0",
    "summary": "Automatically calculates latitude and longitude for customers and enables distance-based delivery",
    "description": """
        This module automatically calculates the latitude and longitude of a customer when their address is updated.
        Useful for website orders and delivery management.
    """,
    "category": "Website/Delivery",
    "author": "Vidyasree M A",
    "website": "https://thecutuae.com",
    "depends": [
        "base",
        "sale",
        "website",
        "website_sale",
        "delivery",
        "base_geolocalize"
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/res_company_inherit.xml",
        "views/sale_order_inherit.xml",
        "views/delivery_zone.xml",
        "views/zone_warning.xml",
        "views/map_templates.xml",
        "views/billing_address_template_inherit.xml",
        "views/sale_order_report_inherit.xml"
    ],
    "assets": {
        "web.assets_backend": [
            # Google Maps is loaded dynamically in polygon_map_widget.js
            # No external libraries needed
            "website_delivery_geolocation/static/src/xml/polygon_map_widget.xml",
            "website_delivery_geolocation/static/src/js/polygon_map_widget.js",
            # "website_delivery_geolocation/static/src/css/map_style.css",
            # "website_delivery_geolocation/static/src/js/map_selector.js",
        ],
        "web.assets_frontend": [
            # Frontend assets for the map selector on checkout
            "website_delivery_geolocation/static/src/css/map_style.css",
            "website_delivery_geolocation/static/src/js/map_selector.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}