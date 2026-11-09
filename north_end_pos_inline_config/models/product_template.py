from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Extend the existing field: retain the existing relation and all mappings.
    pos_optional_product_ids = fields.Many2many(string='Add-ons')

    @api.model
    def _load_pos_data_fields(self, config):
        names = super()._load_pos_data_fields(config)
        return names + ['sale_ok'] if 'sale_ok' not in names else names
