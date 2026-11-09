from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PosConfig(models.Model):
    _inherit = 'pos.config'

    ne_inline_enabled = fields.Boolean(string='Inline variants and add-ons', default=True)
    ne_addon_limit = fields.Integer(
        string='Maximum portions per add-on', default=50,
        help='Maximum quantity of each add-on on one coffee line. Zero means unlimited.',
    )

    @api.model
    def _load_pos_data_fields(self, config):
        names = super()._load_pos_data_fields(config)
        # Core pos.config loads all fields by returning an empty list.
        return names + ['ne_inline_enabled', 'ne_addon_limit'] if names else names

    @api.constrains('ne_addon_limit')
    def _check_ne_addon_limit(self):
        if any(config.ne_addon_limit < 0 for config in self):
            raise ValidationError(_('The add-on limit cannot be negative.'))
