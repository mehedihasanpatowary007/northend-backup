from odoo import api, models


class ProductTemplateAttributeValue(models.Model):
    _inherit = 'product.template.attribute.value'

    @api.model
    def _load_pos_data_fields(self, config):
        names = super()._load_pos_data_fields(config)
        # Native on-demand product loading includes retained inactive values.
        # Send their status so the inline editor can exclude them consistently.
        return names + ['ptav_active'] if 'ptav_active' not in names else names
