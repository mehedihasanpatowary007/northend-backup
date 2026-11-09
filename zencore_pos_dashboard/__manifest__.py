{
    'name': 'POS Dashboard',
    'version': '19.0.1.0.14',
    'category': 'Point of Sale',
    'summary': 'Backend POS sales dashboard with filters and order intelligence',
    'depends': ['point_of_sale', 'pos_hr', 'web'],
    'data': [
        'views/pos_dashboard_views.xml',
        'views/dashboard_target_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'zencore_pos_dashboard/static/src/dashboard.js',
            'zencore_pos_dashboard/static/src/dashboard.xml',
            'zencore_pos_dashboard/static/src/dashboard.scss',
        ],
    },
    'license': 'LGPL-3',
    'icon': 'static/description/icon.png',
    'installable': True,
    'application': True,
}
