import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

const labels = {
    line_percent: _t("Line % Discount"), line_fixed: _t("Line Fixed Discount"),
    global_percent: _t("Order % Discount"), global_fixed: _t("Order Fixed Discount"),
};
const isDiscount = (mode) => Object.hasOwn(labels, mode);

export function canEditDiscount(pos, global = false) {
    const order = pos.getOrder();
    const line = order?.getSelectedOrderline();
    return Boolean(order && order.state === "draft" && !order.isRefund && !order.payment_ids.length &&
        pos.config.manual_discount && pos.cashier?._role !== "minimal" &&
        !pos.restrictLineDiscountChange() &&
        (global ? order.lines.some((item) => item.qty > 0 && item.price_unit > 0) :
            line && !line.isTipLine() && !line.is_reward_line && !line.combo_parent_id));
}

export function activateDiscount(component, mode) {
    if (!canEditDiscount(component.pos, mode.startsWith("global_"))) return;
    component.numberBuffer.capture();
    component.numberBuffer.reset();
    component.pos.getOrder().uiState.neDiscountHint = "";
    component.pos.numpadMode = mode;
}

patch(ProductScreen.prototype, {
    getNumpadButtons() {
        return super.getNumpadButtons(...arguments).map((button) => button.value !== "discount" ? button :
            { ...button, value: "line_percent", text: _t("%"), disabled: !canEditDiscount(this.pos),
                class: `${button.class} ${this.pos.numpadMode === "line_percent" ? "active" : ""}` });
    },
    onNumpadClick(value) {
        if (value === "discount") value = "line_percent";
        if (isDiscount(value)) return activateDiscount(this, value);
        return super.onNumpadClick(value);
    },
    neDiscountMode(mode) { activateDiscount(this, mode); },
    neCanOrderDiscount() { return canEditDiscount(this.pos, true); },
    neCanLineDiscount() { return canEditDiscount(this.pos); },
    get neEditingLabel() { return labels[this.pos.numpadMode] || ""; },
    get neEditingValue() {
        const order = this.currentOrder;
        const line = order?.getSelectedOrderline();
        return this.pos.numpadMode.startsWith("global_") ? order?.global_discount_input_value || 0 :
            this.pos.numpadMode === "line_fixed" ? line?.getFixedDiscountAmount() || 0 : line?.discount || 0;
    },
});

patch(OrderSummary.prototype, {
    updateSelectedOrderline({ buffer, key }) {
        const mode = this.pos.numpadMode;
        if (!isDiscount(mode)) return super.updateSelectedOrderline(...arguments);
        const order = this.currentOrder;
        if (!canEditDiscount(this.pos, mode.startsWith("global_"))) {
            order.uiState.neDiscountHint = _t("Discount editing is unavailable. Select an item or check permissions and payments.");
            this.numberBuffer.reset();
            return;
        }
        const text = buffer === null || buffer === "" ? "0" : String(buffer);
        const normalized = text.replace(this.env.services.localization.decimalPoint, ".");
        if (!/^\d+(\.\d*)?$/.test(normalized) || !Number.isFinite(Number(normalized))) {
            order.uiState.neDiscountHint = _t("Enter a valid non-negative discount.");
            this.numberBuffer.reset();
            return;
        }
        let amount = Number(normalized);
        const percent = mode.endsWith("percent");
        const line = order.getSelectedOrderline();
        const maximum = percent ? 100 : mode === "line_fixed" ? line.getFixedDiscountBaseAmount() :
            Math.max(0, order.neGrossBeforeGlobal);
        const requested = amount;
        amount = Math.min(amount, maximum);
        try {
            if (mode.startsWith("global_")) order.setGlobalDiscount(percent ? "percent" : "fixed", amount);
            else if (mode === "line_fixed") line.setFixedDiscountAmount(amount);
            else this.pos.setDiscountFromUI(line, amount);
            order.uiState.neDiscountHint = requested > maximum ? _t("Discount capped at the available maximum.") : "";
        } catch (error) {
            order.uiState.neDiscountHint = error.message;
        }
    },
    clickLine() {
        this.numberBuffer.capture();
        return super.clickLine(...arguments);
    },
});

patch(PosStore.prototype, {
    setOrder(order) {
        this.env.services.number_buffer?.capture();
        this.env.services.number_buffer?.reset();
        if (isDiscount(this.numpadMode)) this.numpadMode = "quantity";
        return super.setOrder(...arguments);
    },
    pay() {
        this.env.services.number_buffer.capture();
        this.env.services.number_buffer.reset();
        this.numpadMode = "quantity";
        return super.pay(...arguments);
    },
});
