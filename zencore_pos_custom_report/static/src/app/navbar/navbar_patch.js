import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { patch } from "@web/core/utils/patch";

patch(Navbar.prototype, {
    openWaiterCashierReport() {
        const configId = this.pos.config?.id || "";
        const sessionId = this.pos.session?.id || this.pos.pos_session?.id || "";
        window.open(`/pos/waiter_cashier_report?config_id=${configId}&session_id=${sessionId}`, "_blank");
    },
    openItemsSalesReport() {
        const configId = this.pos.config?.id || "";
        const sessionId = this.pos.session?.id || this.pos.pos_session?.id || "";
        window.open(`/pos/items_sales_report?config_id=${configId}&session_id=${sessionId}`, "_blank");
    },
    openWorkPeriodSalesSummary() {
        const configId = this.pos.config?.id || "";
        const sessionId = this.pos.session?.id || this.pos.pos_session?.id || "";
        window.open(`/pos/work_period_sales_summary?config_id=${configId}&session_id=${sessionId}`, "_blank");
    },
});
