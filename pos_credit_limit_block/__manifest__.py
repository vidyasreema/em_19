{
    "name": "POS Credit Limit Block",
    "version": "19.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Block the Customer Account payment method when a customer exceeds their credit limit",
    "depends": ["point_of_sale", "account"],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_credit_limit_block/static/src/overrides/payment_screen.js",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
}