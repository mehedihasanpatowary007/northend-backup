from odoo import fields, models


class PosOrderReport(models.Model):
    _inherit = "report.pos.order"

    fixed_discount_amount = fields.Float(string="Fixed Discount", readonly=True)
    global_discount_amount = fields.Float(string="Global Discount", readonly=True)

    def _select(self):
        select_query = super()._select()
        currency_rate = "COALESCE(NULLIF(s.currency_rate, 0), 1.0)"
        percentage_discount = f"(l.qty * l.price_unit) * (l.discount / 100) / {currency_rate}"
        fixed_discount = (
            "CASE "
            "WHEN (l.qty * l.price_unit) < 0 "
            "THEN -COALESCE(l.fixed_discount_amount, 0) "
            "ELSE COALESCE(l.fixed_discount_amount, 0) "
            f"END / {currency_rate}"
        )
        global_discount = f"COALESCE(l.global_discount_allocation, 0) / {currency_rate}"
        return select_query.replace(
            f"{percentage_discount} AS total_discount,",
            (
                f"({percentage_discount} + {fixed_discount} + {global_discount}) AS total_discount,\n"
                f"                {fixed_discount} AS fixed_discount_amount,"
                f"\n                {global_discount} AS global_discount_amount,"
            ),
        )
