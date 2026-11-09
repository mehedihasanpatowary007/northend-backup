from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    pos_is_mfs = fields.Boolean(
        string="Show under MFS in POS",
        help=(
            "Show this payment method in a separate MFS section on the POS payment screen. "
            "MFS methods must use a Bank journal for standard Odoo accounting."
        ),
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return [*super()._load_pos_data_fields(config), "pos_is_mfs"]

    @api.constrains("pos_is_mfs", "journal_id")
    def _check_mfs_bank_journal(self):
        for method in self:
            if method.pos_is_mfs and (
                not method.journal_id or method.journal_id.type != "bank"
            ):
                raise ValidationError(
                    _("MFS payment methods must use a Bank journal.")
                )
