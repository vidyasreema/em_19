{
    "name": "POS LPO Number",
    "version": "19.0.1.0.0",
    "depends": ["point_of_sale", "account"],
    "data": [
        "views/pos_order_views.xml",
        "report/invoice_report.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_lpo_note/static/src/app/models/pos_order.js",
            "pos_lpo_note/static/src/app/screens/product_screen/control_buttons/control_buttons.js",
            "pos_lpo_note/static/src/app/screens/product_screen/control_buttons/control_buttons.xml",
        ],
    },
    "installable": True,
    "license": "LGPL-3",
}
