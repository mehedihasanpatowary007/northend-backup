{
    'name': 'Inter-Company Internal Transfer',
    'version': '19.0.1.0.0',
    'summary': 'Linked inter-company internal transfers with transit accounting',
    'description': 'Inter-company transfer workflow synchronized with Odoo Internal Transfers.',
    'category': 'Inventory/Inventory',
    'author': 'Mehedi Hasan, ZenCore',
    'license': 'LGPL-3',
    'depends': ['stock_account'],
    'data': [
        'data/intercompany_data.xml',
        'views/stock_picking_views.xml',
        'views/settings_views.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
