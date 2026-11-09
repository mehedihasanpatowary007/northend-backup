{
    "name": "North End POS Line and Global Discounts",
    "version": "19.0.2.0.7",
    "category": "Sales/Point of Sale",
    "summary": "Direct line and tax-aware global discounts using the existing POS keypad",
    "author": "Mehedi Hasan",
    "website": "https://zencoreltd.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "views/pos_order_views.xml",
        "views/global_discount_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "zencore_custom_pos_fixed_discount/static/src/js/pos_order_line_fixed_discount.js",
            "zencore_custom_pos_fixed_discount/static/src/js/discount_math.js",
            "zencore_custom_pos_fixed_discount/static/src/js/global_discount.js",
            "zencore_custom_pos_fixed_discount/static/src/js/discount_controls.js",
            "zencore_custom_pos_fixed_discount/static/src/js/payment_screen_fixed_discount.js",
            "zencore_custom_pos_fixed_discount/static/src/xml/**/*.xml",
            "zencore_custom_pos_fixed_discount/static/src/scss/discount_controls.scss",
            "zencore_custom_pos_fixed_discount/static/src/scss/payment_screen_cash_quick_amounts.scss",
        ],
    },
    "installable": True,
    "application": False,
}
