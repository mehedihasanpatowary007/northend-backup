from odoo import fields, models, _
from odoo.exceptions import AccessError


class ResUsers(models.Model):
    _inherit = 'res.users'

    pos_markout_allowed_category_ids = fields.Many2many(
        'pos.markout.category', 'pos_markout_user_category_rel', 'user_id', 'category_id',
        string='Allowed Marked Out Subcategories',
        domain="[('parent_id', '!=', False)]")
    pos_markout_can_view = fields.Boolean(string='View Marked Out')
    pos_markout_can_create = fields.Boolean(string='Create / Confirm Marked Out')
    pos_markout_can_manage_categories = fields.Boolean(string='Manage Categories / Benefit Rules')
    pos_markout_can_reverse = fields.Boolean(string='Reverse Marked Out (Reserved)', default=False)
    pos_markout_can_view_reports = fields.Boolean(string='View Marked Out Reports')

    def write(self, vals):
        restricted = {
            'pos_markout_allowed_category_ids', 'pos_markout_can_view', 'pos_markout_can_create',
            'pos_markout_can_manage_categories', 'pos_markout_can_reverse', 'pos_markout_can_view_reports',
        }
        if restricted.intersection(vals) and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only an administrator can change Marked Out access rights.'))
        return super().write(vals)
