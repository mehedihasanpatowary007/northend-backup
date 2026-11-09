from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        copy=False,
        index=True,
        ondelete='set null',
    )
