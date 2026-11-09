import math

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    fixed_discount_amount = fields.Monetary(
        string="Fixed Disc",
        currency_field="currency_id",
        default=0.0,
        help="Fixed discount amount applied on this POS order line after the percentage discount.",
    )

    @api.constrains("fixed_discount_amount")
    def _check_fixed_discount_amount(self):
        for line in self:
            if not math.isfinite(line.fixed_discount_amount):
                raise ValidationError(_("Fixed discount must be a finite number."))
            if float_compare(
                line.fixed_discount_amount or 0.0,
                0.0,
                precision_rounding=line.currency_id.rounding or 0.01,
            ) < 0:
                raise ValidationError(_("Fixed discount cannot be negative."))

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_to_load = super()._load_pos_data_fields(config_id)
        # Preserve Odoo's empty-list sentinel: it already includes custom fields.
        if not fields_to_load:
            return fields_to_load
        return list(dict.fromkeys([*fields_to_load, "fixed_discount_amount"]))

    def _get_fixed_discount_for_quantity(self, quantity):
        self.ensure_one()
        if not self.qty:
            return 0.0
        amount = max(self.fixed_discount_amount or 0.0, 0.0)
        return amount * abs(quantity / self.qty)

    def _get_fixed_discount_adjusted_price_unit(self, quantity, base_line=None):
        self.ensure_one()
        price_unit = self.price_unit
        discount = min(max(self.discount or 0.0, 0.0), 100.0)
        discount_factor = 1.0 - (discount / 100.0)

        if not quantity or not discount_factor:
            return price_unit

        Tax = self.env['account.tax']
        if base_line:
            base_line = {**base_line, 'quantity': quantity, 'price_unit': price_unit}
        else:
            base_line = Tax._prepare_base_line_for_taxes_computation(
                self,
                price_unit=price_unit,
                quantity=quantity,
                discount=discount,
                tax_ids=self.tax_ids_after_fiscal_position,
                product_id=self.product_id,
                product_uom_id=self.product_id.uom_id,
                currency_id=self.order_id.currency_id,
                partner_id=self.order_id.partner_id,
                is_refund=self.order_id.is_refund,
            )
        Tax._add_tax_details_in_base_line(base_line, self.order_id.company_id)
        gross_total = base_line['tax_details']['raw_total_included_currency']
        fixed_discount = min(self._get_fixed_discount_for_quantity(quantity), abs(gross_total))
        if not fixed_discount:
            return price_unit

        sign = -1.0 if gross_total < 0.0 else 1.0
        return self._ne_price_for_gross(base_line, gross_total - sign * fixed_discount)

    @api.onchange("price_unit", "tax_ids", "qty", "discount", "fixed_discount_amount", "product_id")
    def _onchange_amount_line_all(self):
        for line in self:
            res = line._compute_amount_line_all()
            line.update(res)

    def _compute_amount_line_all(self):
        self.ensure_one()
        fpos = self.order_id.fiscal_position_id
        tax_ids_after_fiscal_position = fpos.map_tax(self.tax_ids)
        base_line = self.env['account.tax']._prepare_base_line_for_taxes_computation(
            self,
            price_unit=self.price_unit,
            quantity=self.qty,
            discount=self.discount,
            tax_ids=tax_ids_after_fiscal_position,
            product_id=self.product_id,
            product_uom_id=self.product_id.uom_id,
            currency_id=self.order_id.currency_id,
            partner_id=self.order_id.partner_id,
            is_refund=self.order_id.is_refund,
        )
        price = self._get_fixed_discount_adjusted_price_unit(self.qty, base_line) * (
            1 - (self.discount or 0.0) / 100.0
        )
        taxes = tax_ids_after_fiscal_position.compute_all(
            price,
            self.order_id.currency_id,
            self.qty,
            product=self.product_id,
            partner=self.order_id.partner_id,
        )
        return {
            "price_subtotal_incl": taxes["total_included"],
            "price_subtotal": taxes["total_excluded"],
        }

    @api.onchange("qty", "discount", "fixed_discount_amount", "price_unit", "tax_ids")
    def _onchange_qty(self):
        if self.product_id:
            price = self._get_fixed_discount_adjusted_price_unit(self.qty) * (
                1 - (self.discount or 0.0) / 100.0
            )
            self.price_subtotal = self.price_subtotal_incl = price * self.qty
            if self.tax_ids:
                taxes = self.tax_ids_after_fiscal_position.compute_all(
                    price,
                    self.order_id.currency_id,
                    self.qty,
                    product=self.product_id,
                    partner=False,
                )
                self.price_subtotal = taxes["total_excluded"]
                self.price_subtotal_incl = taxes["total_included"]

    def _prepare_base_line_for_taxes_computation(self):
        base_line = super()._prepare_base_line_for_taxes_computation()
        quantity = base_line.get("quantity", self.qty)
        base_line["price_unit"] = self._get_fixed_discount_adjusted_price_unit(quantity, base_line)
        return base_line

    def _prepare_refund_data(self, refund_order, PosOrderLineLot):
        values = super()._prepare_refund_data(refund_order, PosOrderLineLot)
        values["fixed_discount_amount"] = self.fixed_discount_amount
        return values
