import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { allocateDiscount, refundShare, priceForGross } from "./discount_math";

PosOrder.accountingFields = new Set([...PosOrder.accountingFields,
    "global_discount_type", "global_discount_input_value"]);
PosOrderline.accountingFields = new Set([...PosOrderline.accountingFields,
    "fixed_discount_amount", "global_discount_allocation"]);

patch(PosOrder.prototype, {
    setup(vals) {
        // Client-created/offline records do not receive Python field defaults.
        // Set them before accounting setup computes the initial order prices.
        this.global_discount_type = this.global_discount_type || "none";
        this.global_discount_input_value = this.global_discount_input_value || 0;
        super.setup(...arguments);
    },

    setGlobalDiscount(type, value) {
        this.assertEditable();
        const previous = [this.global_discount_type, this.global_discount_input_value];
        this.global_discount_type = value ? type : "none";
        this.global_discount_input_value = value || 0;
        this.triggerRecomputeAllPrices();
        try {
            void this.prices;
        } catch (error) {
            [this.global_discount_type, this.global_discount_input_value] = previous;
            this.triggerRecomputeAllPrices();
            throw error;
        }
        this._markDirty();
    },

    _computeAllPrices(opts = {}) {
        const baselineOpts = { ...(opts.baseLineOpts || {}), ignore_global_discount: true };
        const before = super._computeAllPrices({ ...opts, baseLineOpts: baselineOpts });
        if (opts.baseLineOpts?.ignore_global_discount || opts.baseLineOpts?.discount === 0) {
            return before;
        }
        // Allocate on full-order quantities, including when Odoo computes unit prices or a subset.
        const full = opts.lines || opts.baseLineOpts?.quantity !== undefined
            ? super._computeAllPrices({ baseLineOpts: { ignore_global_discount: true } }) : before;
        const lines = [...this.lines].sort((a, b) => a.uuid < b.uuid ? -1 : a.uuid > b.uuid ? 1 : 0);
        const allocations = allocateDiscount(lines.map((line) => line.refunded_orderline_id ? 0 :
            full.baseLineByLineUuids[line.uuid].tax_details.total_included_currency),
        this.global_discount_type, this.global_discount_input_value || 0, this.currency.rounding);
        const consumed = new Map();
        for (let index = 0; index < lines.length; index++) {
            const source = lines[index].refunded_orderline_id;
            if (source && lines[index].qty < 0) {
                // Include completed earlier refunds, never this draft refund twice.
                const previous = source.refund_orderline_ids.filter((line) =>
                    line.order_id !== this && !["draft", "cancel"].includes(line.order_id.state))
                    .reduce((sum, line) => sum + Math.abs(line.qty), 0) + (consumed.get(source.uuid) || 0);
                allocations[index] = -refundShare(source.global_discount_allocation || 0,
                    source.qty, lines[index].qty, previous, (amount) => this.currency.round(amount));
                consumed.set(source.uuid, (consumed.get(source.uuid) || 0) + Math.abs(lines[index].qty));
            }
        }
        const plan = Object.fromEntries(lines.map((line, index) => [line.uuid, allocations[index]]));
        const key = opts.baseLineOpts?.quantity === 1 ? "unit" : "order";
        this._neBeforeGlobal ||= {};
        this._neBeforeGlobal[key] = before;
        if (key === "order" && !opts.lines) {
            this._neGlobalAllocations = plan;
            this._neGlobalAmount = this.currency.round(allocations.reduce((sum, amount) => sum + amount, 0));
        }
        return super._computeAllPrices({ ...opts,
            baseLineOpts: { ...(opts.baseLineOpts || {}), ne_global_allocations: plan } });
    },

    _constructPriceData(opts = {}) {
        const data = super._constructPriceData(opts);
        if (opts.baseLineOpts?.ignore_global_discount) return data;
        // Keep the standard line discount display independent of hidden global allocations.
        const before = this._neBeforeGlobal?.[opts.baseLineOpts?.quantity === 1 ? "unit" : "order"];
        for (const [uuid, baseLine] of Object.entries(data.baseLineByLineUuids)) {
            const original = before?.baseLineByLineUuids[uuid]?.tax_details;
            if (original) baseLine.tax_details.discount_amount = this.currency.round(
                baseLine.tax_details.no_discount_total_included - original.total_included);
        }
        return data;
    },

    get neGlobalDiscountAmount() {
        void this.prices;
        return this._neGlobalAmount || 0;
    },
    get neGlobalDiscountLabel() {
        return this.isRefund ? _t("Order Discount Reversal") : this.global_discount_type === "percent"
            ? _t("Order Discount (%s%%)", this.global_discount_input_value) : _t("Order Discount (Fixed)");
    },
    get neGrossBeforeGlobal() {
        void this.prices;
        return this._neBeforeGlobal?.order?.taxDetails.total_amount_no_rounding || 0;
    },
    // Presentation uses the pre-order-discount snapshot so Subtotal + Taxes = Total.
    // The Grand Total and included-tax note continue to use the actual final prices.
    get neSummarySubtotal() {
        void this.prices;
        return this.neGlobalDiscountAmount ? this._neBeforeGlobal.order.taxDetails.base_amount : this.priceExcl;
    },
    get neSummaryTax() {
        void this.prices;
        return this.neGlobalDiscountAmount ? this._neBeforeGlobal.order.taxDetails.tax_amount_currency : this.amountTaxes;
    },
    get neSummaryGross() {
        return this.neGlobalDiscountAmount ? this.neGrossBeforeGlobal : this.priceIncl;
    },
    setOrderPrices() {
        super.setOrderPrices(...arguments);
        this.global_discount_amount = this.neGlobalDiscountAmount;
        for (const line of this.lines) {
            line.global_discount_allocation = this._neGlobalAllocations?.[line.uuid] || 0;
        }
    },
});

patch(PosOrderline.prototype, {
    prepareBaseLineForTaxesComputationExtraValues(customValues = {}) {
        const values = super.prepareBaseLineForTaxesComputationExtraValues(...arguments);
        if (customValues.ignore_global_discount || !this.qty) return values;
        const allocation = customValues.ne_global_allocations?.[this.uuid] || 0;
        if (!allocation) return values;
        const baseLine = accountTaxHelpers.prepare_base_line_for_taxes_computation(this, values);
        const details = accountTaxHelpers.get_tax_details(values.tax_ids,
            values.price_unit * (1 - values.discount / 100), values.quantity,
            { rounding_method: "round_globally", product: values.product_id, product_uom: values.product_uom_id });
        values.price_unit = priceForGross(baseLine,
            details.total_included - allocation * values.quantity / this.qty, accountTaxHelpers);
        return values;
    },
    get displayPrice() {
        void this.order_id.prices;
        const before = this.order_id._neBeforeGlobal?.order?.baseLineByLineUuids[this.uuid]?.tax_details;
        if (!before) return super.displayPrice;
        if (this.combo_line_ids.length) return this.combo_line_ids.reduce((sum, line) => sum + line.displayPrice, 0);
        return this.currency.round((this.config.iface_tax_included === "total" ? before.total_included : before.total_excluded) * this.order_id.orderSign);
    },
    get displayPriceUnit() {
        void this.order_id.unitPrices;
        const before = this.order_id._neBeforeGlobal?.unit?.baseLineByLineUuids[this.uuid]?.tax_details;
        return before ? (this.config.iface_tax_included === "total" ? before.total_included : before.total_excluded)
            : super.displayPriceUnit;
    },
});
