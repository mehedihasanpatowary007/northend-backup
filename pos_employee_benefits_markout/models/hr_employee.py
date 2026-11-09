from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    pos_benefit_rule_ids = fields.One2many(
        'pos.benefit.rule', 'employee_id', string='POS Benefits',
        groups='hr.group_hr_manager,point_of_sale.group_pos_manager',
        help='Employee-specific daily allowances. Shared default rules are configured in Point of Sale / Marked Out / Setup / Benefit Rules.')

    # Retained only to preserve existing installations' old mapping data during
    # upgrades. Marked Out uses Odoo's barcode and work_contact_id exclusively;
    # these values are never copied over the native employee fields.
    pos_markout_badge_id = fields.Char(
        string='Legacy POS Benefit Badge ID', copy=False, readonly=True,
        groups='hr.group_hr_user',
        help='Unused legacy value. Marked Out uses the standard employee Badge ID.')
    pos_markout_partner_id = fields.Many2one(
        'res.partner', string='Legacy POS Benefit Customer', copy=False, readonly=True,
        groups='hr.group_hr_user',
        help='Unused legacy value. Marked Out uses the standard employee Work Contact.')
