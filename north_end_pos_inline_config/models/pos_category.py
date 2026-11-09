from odoo import api, models, _
from odoo.exceptions import ValidationError

HEX_COLOR_OFFSET = 0x1000000
MAX_HEX_COLOR = HEX_COLOR_OFFSET + 0xFFFFFF


class PosCategory(models.Model):
    _inherit = "pos.category"

    @api.constrains("color")
    def _check_pos_color_value(self):
        for category in self:
            color = category.color or 0
            if color < 0 or 12 <= color < HEX_COLOR_OFFSET or color > MAX_HEX_COLOR:
                raise ValidationError(
                    _("Use one of the standard colors or a valid six-digit HEX color.")
                )
