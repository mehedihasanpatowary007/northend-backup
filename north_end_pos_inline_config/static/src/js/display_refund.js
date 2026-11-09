import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";
import { formatCurrency } from "@web/core/currency";

patch(Orderline, {
    props: { ...Orderline.props, neGrouped: { type: Boolean, optional: true } },
});
patch(Orderline.prototype, {
    neAmount(amount) {
        return formatCurrency(amount, this.line.currency.id);
    },
});

patch(TicketScreen.prototype, {
    postRefund(order) {
        super.postRefund(...arguments);
        const refunds = new Map(order.lines.filter((line) => line.refunded_orderline_id)
            .map((line) => [line.refunded_orderline_id.uuid, line]));
        for (const line of order.lines) {
            const source = line.refunded_orderline_id;
            if (!source) continue;
            if (source.ne_parent_uuid) {
                const parent = refunds.get(source.ne_parent_uuid);
                line.update({ ne_parent_uuid: parent?.uuid || false, ne_parent_label: source.ne_parent_label });
            }
            if (source.getFixedDiscountAmount?.() && source.qty) {
                line.setFixedDiscountAmount?.(source.getFixedDiscountAmount() * Math.abs(line.qty / source.qty));
            }
        }
        order.triggerRecomputeAllPrices?.();
    },
});
