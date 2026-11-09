import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup();
        this.accordionState = useState({
            activeType: null,
        });
    },

    toggleAccordion(type) {
        if (this.accordionState.activeType === type) {
            this.accordionState.activeType = null;
        } else {
            this.accordionState.activeType = type;
        }
    },

    get groupedPaymentMethods() {
        const typeMeta = {
            bank: {
                label: "Bank",
                iconClass: "fa-credit-card text-primary",
            },
            cash: {
                label: "Cash",
                iconClass: "fa-money text-success",
            },
            mfs: {
                label: "MFS",
                iconClass: "fa-mobile text-info",
            },
            pay_later: {
                label: "Customer Account",
                iconClass: "fa-user text-info",
            },
        };

        const groups = {};
        const methods = this.payment_methods_from_config || [];

        for (const method of methods) {
            const mType = method.pos_is_mfs ? "mfs" : method.type || "other";
            if (!groups[mType]) {
                const meta = typeMeta[mType] || {
                    label: mType.charAt(0).toUpperCase() + mType.slice(1).replace("_", " "),
                    iconClass: "fa-credit-card text-secondary",
                };
                groups[mType] = {
                    type: mType,
                    label: meta.label,
                    iconClass: meta.iconClass,
                    methods: [],
                };
            }
            groups[mType].methods.push(method);
        }

        const preferredOrder = ["bank", "cash", "mfs", "pay_later"];
        return Object.values(groups).sort((a, b) => {
            const idxA = preferredOrder.indexOf(a.type);
            const idxB = preferredOrder.indexOf(b.type);
            if (idxA !== -1 && idxB !== -1) return idxA - idxB;
            if (idxA !== -1) return -1;
            if (idxB !== -1) return 1;
            return a.label.localeCompare(b.label);
        });
    },
});
