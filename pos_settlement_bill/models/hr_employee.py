from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    pos_settlement_bill_allowed = fields.Boolean(
        string='Print Settlement Bills',
        default=False,
        copy=False,
        groups='hr.group_hr_manager',
        help='Allow this employee to print an unpaid settlement bill after '
             'entering their existing employee PIN. Permission is checked '
             'on the server for every print request.',
    )
    pos_settlement_pin_failures = fields.Integer(
        default=0,
        copy=False,
        readonly=True,
        groups='base.group_system',
    )
    pos_settlement_pin_locked_until = fields.Datetime(
        copy=False,
        readonly=True,
        groups='base.group_system',
    )
