import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { formatCurrency } from "@web/core/currency";
import { roundPrecision } from "@web/core/utils/numbers";
import { parseFloat as parseFloatField } from "@web/views/fields/parsers";
import { patch } from "@web/core/utils/patch";
import { priceForGross } from "./discount_math";

const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

patch(PosOrderline.prototype, {
    setup(vals) {
        super.setup(...arguments);
        const source = this.refunded_orderline_id;
        this.fixed_discount_amount = source?.qty && this.qty < 0
            ? (source.fixed_discount_amount || 0) * Math.abs(this.qty / source.qty)
            : vals.fixed_discount_amount || 0;
        this.order_id?.triggerRecomputeAllPrices?.();
    },

    _markFixedDiscountDirty() {
        // Odoo 19 caches the order's tax and total calculations separately
        // from the model's dirty state. Invalidate that cache whenever this
        // custom amount changes so the cart and payment total are refreshed.
        this.order_id?.triggerRecomputeAllPrices?.();
        this.order_id?._markDirty?.();
        this._markDirty?.();
    },

    setFixedDiscountAmount(amount) {
        const parsedAmount =
            typeof amount === "number"
                ? amount
                : isNaN(parseFloatField(amount))
                ? 0
                : parseFloatField(amount);
        const cappedAmount = this.getCappedFixedDiscountAmount(parsedAmount || 0);
        this.fixed_discount_amount = roundPrecision(cappedAmount, this.currency.rounding);
        this._markFixedDiscountDirty();
        return this.fixed_discount_amount;
    },

    set_fixed_discount_amount(amount) {
        return this.setFixedDiscountAmount(amount);
    },

    getFixedDiscountAmount() {
        return this.getCappedFixedDiscountAmount(this.fixed_discount_amount || 0);
    },

    get_fixed_discount_amount() {
        return this.getFixedDiscountAmount();
    },

    getFixedDiscountForQuantity(quantity = this.getQuantity()) {
        if (!this.getQuantity()) {
            return 0;
        }
        return this.getFixedDiscountAmount() * Math.abs(quantity / this.getQuantity());
    },

    get_fixed_discount_for_quantity(quantity = this.getQuantity()) {
        return this.getFixedDiscountForQuantity(quantity);
    },

    getCappedFixedDiscountAmount(amount) {
        const parsedAmount = Math.max(amount || 0, 0);
        return Math.min(parsedAmount, this.getFixedDiscountBaseAmount());
    },

    get_capped_fixed_discount_amount(amount) {
        return this.getCappedFixedDiscountAmount(amount);
    },

    getFixedDiscountBaseAmount(quantity = this.getQuantity()) {
        const baseLine = this.getBaseLine({
            quantity,
            ignore_fixed_discount: true,
            ignore_global_discount: true,
        });
        const discountFactor = 1 - baseLine.discount / 100;
        if (!quantity || !discountFactor) {
            return 0;
        }
        const details = accountTaxHelpers.get_tax_details(
            baseLine.tax_ids,
            baseLine.price_unit * discountFactor,
            quantity,
            {
                rounding_method: "round_globally",
                product: baseLine.product_id,
                product_uom: baseLine.product_uom_id,
            }
        );
        return Math.abs(details.total_included);
    },

    get_fixed_discount_base_amount(quantity = this.getQuantity()) {
        return this.getFixedDiscountBaseAmount(quantity);
    },

    prepareBaseLineForTaxesComputationExtraValues(customValues = {}) {
        const values = super.prepareBaseLineForTaxesComputationExtraValues?.(customValues) || {};
        if (
            customValues.ignore_fixed_discount ||
            (hasOwn(customValues, "discount") && customValues.discount === 0.0) ||
            (hasOwn(customValues, "price_unit") && customValues.price_unit !== this.price_unit)
        ) {
            return values;
        }

        const quantity = values.quantity || 0;
        const discount = values.discount || 0;
        const discountFactor = 1 - discount / 100;
        if (!quantity || !discountFactor) {
            return values;
        }

        const baseLine = accountTaxHelpers.prepare_base_line_for_taxes_computation(this, values);
        const taxOptions = {
            rounding_method: "round_globally",
            product: values.product_id,
            product_uom: values.product_uom_id,
        };
        const beforeDiscount = accountTaxHelpers.get_tax_details(
            values.tax_ids,
            values.price_unit * discountFactor,
            quantity,
            taxOptions
        );
        const fixedDiscount = Math.min(this.getFixedDiscountForQuantity(quantity),
            Math.abs(beforeDiscount.total_included));
        if (!fixedDiscount) {
            return values;
        }

        const sign = beforeDiscount.total_included < 0 ? -1 : 1;
        values.price_unit = priceForGross(
            baseLine,
            beforeDiscount.total_included - sign * fixedDiscount,
            accountTaxHelpers
        );
        return values;
    },

    setDiscount(discount) {
        super.setDiscount(discount);
        this.fixed_discount_amount = this.getFixedDiscountAmount();
        this._markFixedDiscountDirty();
    },

    set_discount(discount) {
        return this.setDiscount(discount);
    },

    setQuantity(quantity, keep_price) {
        const result = super.setQuantity(...arguments);
        if (result === true) {
            this.fixed_discount_amount = this.getFixedDiscountAmount();
            this._markFixedDiscountDirty();
        }
        return result;
    },

    set_quantity(quantity, keep_price) {
        return this.setQuantity(...arguments);
    },

    setUnitPrice(price) {
        super.setUnitPrice(...arguments);
        this.fixed_discount_amount = this.getFixedDiscountAmount();
        this._markFixedDiscountDirty();
    },

    set_unit_price(price) {
        return this.setUnitPrice(...arguments);
    },

    canBeMergedWith(orderline) {
        return !this.getFixedDiscountAmount() && !orderline.getFixedDiscountAmount() && super.canBeMergedWith(orderline);
    },

    can_be_merged_with(orderline) {
        return this.canBeMergedWith(orderline);
    },

    get fixedDiscountAmount() {
        const fixedDiscount = this.getFixedDiscountAmount();
        return fixedDiscount ? formatCurrency(fixedDiscount, this.currency.id) : "";
    },

    getDisplayData() {
        const data = super.getDisplayData?.() || {};
        return { ...data, fixedDiscountAmount: this.fixedDiscountAmount };
    },
});
