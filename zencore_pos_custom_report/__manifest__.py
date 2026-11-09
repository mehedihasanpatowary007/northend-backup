{
    'name': 'Zencore POS Custom Report',
    'version': '19.0.1.1.0',
    'category': 'Point of Sale',
    'summary': 'Daily financial collection and cashier breakdown report in POS UI',
    'description': """
        Adds a 'Waiter Cashier Report' button in the POS navbar burger menu.
        Opens today's financial summary report in a new tab with payment gateway breakdowns,
        user-wise settlement, and Excel (.xlsx) export capability.
    """,
    'author': 'Antigravity Odoo Developer',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'mail'],
    'data': [
        'views/report_template.xml',
        'views/report_items_sales_template.xml',
        'views/report_work_period_sales_summary_template.xml',
        'views/pos_dashboard_views.xml',
        'views/pos_session_views.xml',
        'views/pos_payment_method_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'zencore_pos_custom_report/static/src/app/payment_screen/payment_screen_accordion.css',
            'zencore_pos_custom_report/static/src/app/payment_screen/payment_screen_accordion.xml',
            'zencore_pos_custom_report/static/src/app/payment_screen/payment_screen_accordion.js',
            'zencore_pos_custom_report/static/src/app/navbar/navbar_patch.js',
            'zencore_pos_custom_report/static/src/app/navbar/navbar.xml',
            'zencore_pos_custom_report/static/src/app/closing_popup/closing_popup_patch.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
