import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    onMounted() {
        // Ensure the amount due reflects custom fixed discounts before the
        // payment screen creates its default payment line.
        const order = this.currentOrder;
        if (order) {
            order.triggerRecomputeAllPrices?.();
            void order.remainingDue;
        }
        return super.onMounted(...arguments);
    },

    addQuickCashAmount(amount) {
        const currentBuffer = this.numberBuffer.get();
        const currentAmount = currentBuffer ? this.numberBuffer.getFloat() : 0;
        const precision = this.pos.currency.decimal_places ?? 2;
        const nextAmount = Number((currentAmount + amount).toFixed(precision));

        // Keep the number buffer and selected payment line synchronized, just
        // like the built-in +10/+20/+50 keypad shortcuts.
        this.numberBuffer.set(String(nextAmount));
        this.updateSelectedPaymentline(nextAmount);
    },
});
