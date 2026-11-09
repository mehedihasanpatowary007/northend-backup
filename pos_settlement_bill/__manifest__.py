{
    'name': 'POS Settlement Bill',
    'version': '19.0.1.1.4',
    'category': 'Sales/Point of Sale',
    'summary': 'Print a clean unpaid table bill with employee permission and PIN approval',
    'author': 'ZenCore',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'pos_hr'],
    'data': [
        'views/hr_employee_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_settlement_bill/static/src/app/order_note.js',
            'pos_settlement_bill/static/src/app/order_note.xml',
            'pos_settlement_bill/static/src/app/order_note.scss',
            'pos_settlement_bill/static/src/app/settlement_receipt.js',
            'pos_settlement_bill/static/src/app/settlement_receipt.xml',
            'pos_settlement_bill/static/src/app/settlement_receipt.scss',
            'pos_settlement_bill/static/src/app/settlement_button.js',
            'pos_settlement_bill/static/src/app/settlement_button.xml',
            'pos_settlement_bill/static/src/app/settlement_button.scss',
        ],
    },
    'installable': True,
    'application': False,
}
