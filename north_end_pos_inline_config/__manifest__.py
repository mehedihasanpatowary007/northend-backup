{
    'name': 'North End POS Inline Configuration',
    'version': '19.0.1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Inline variants, vertical categories and independently counted add-ons',
    'author': 'ZenCore',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'data': ['views/pos_views.xml'],
    'assets': {
        'web.assets_backend': [
            'north_end_pos_inline_config/static/src/backend/pos_category_color_field.js',
            'north_end_pos_inline_config/static/src/backend/pos_category_color_field.xml',
        ],
        'point_of_sale._assets_pos': [
            'north_end_pos_inline_config/static/src/js/*.js',
            'north_end_pos_inline_config/static/src/xml/*.xml',
            'north_end_pos_inline_config/static/src/scss/inline_config.scss',
        ],
    },
    'installable': True,
    'application': False,
}
