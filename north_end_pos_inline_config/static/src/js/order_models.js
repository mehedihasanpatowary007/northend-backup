import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

const sameIds = (left, right) => left.map((record) => record.id).sort((a, b) => a - b).join(",") ===
    right.map((record) => record.id).sort((a, b) => a - b).join(",");

patch(PosOrderline.prototype, {
    neGetParent() {
        return this.ne_parent_uuid && this.order_id?.lines.find((line) => line.uuid === this.ne_parent_uuid);
    },
    neGetAddons() {
        if (!this.uuid) return [];
        return this.order_id?.lines.filter((line) => line.ne_parent_uuid === this.uuid) || [];
    },
    neGroupTotal() {
        return this.displayPrice + this.neGetAddons().reduce((sum, line) => sum + line.displayPrice, 0);
    },
    canBeMergedWith(line) {
        if (!this.order_id.config.ne_inline_enabled && !this.ne_parent_uuid && !line.ne_parent_uuid &&
            !this.neGetAddons().length && !line.neGetAddons().length) {
            return super.canBeMergedWith(...arguments);
        }
        if ((this.ne_parent_uuid || false) !== (line.ne_parent_uuid || false) ||
            this.ne_parent_label && !this.ne_parent_uuid || line.ne_parent_label && !line.ne_parent_uuid ||
            !sameIds(this.tax_ids, line.tax_ids) ||
            !sameIds(this.attribute_value_ids, line.attribute_value_ids) ||
            this.custom_attribute_value_ids.length || line.custom_attribute_value_ids.length ||
            this.getFixedDiscountAmount?.() || line.getFixedDiscountAmount?.() ||
            !this.currency.isZero(this.price_unit - line.price_unit) ||
            this.product_id.tracking !== "none" || this.qty <= 0 || line.qty <= 0) {
            return false;
        }
        const limit = this.order_id.config.ne_addon_limit;
        if (limit) {
            const totals = new Map();
            for (const addon of [...this.neGetAddons(), ...line.neGetAddons()]) {
                totals.set(addon.product_id.id, (totals.get(addon.product_id.id) || 0) + addon.qty);
            }
            if ([...totals.values()].some((qty) => qty > limit)) return false;
        }
        return super.canBeMergedWith(...arguments);
    },
    merge(line) {
        const incoming = [...line.neGetAddons()];
        this.uiState.neMergingUuid = line.uuid;
        try {
            super.merge(...arguments);
        } finally {
            delete this.uiState.neMergingUuid;
        }
        for (const addon of incoming) {
            addon.update({ ne_parent_uuid: this.uuid, ne_parent_label: this.full_product_name });
            const target = this.neGetAddons().find((other) => other !== addon && other.canBeMergedWith(addon));
            if (target) {
                target.merge(addon);
                addon.delete();
            }
        }
    },
    delete() {
        const order = this.order_id;
        for (const addon of [...this.neGetAddons()]) addon.delete();
        const selected = order?.uiState.selected_orderline_uuid === this.uuid;
        const result = super.delete(...arguments);
        if (selected) order.selectOrderline(order.lines.filter((line) => !line.ne_parent_uuid).at(-1));
        return result;
    },
    setQuantity(quantity, keepPrice) {
        if (this.ne_parent_uuid && !this.refunded_orderline_id && Number(quantity) < 0) {
            return { title: _t("Invalid quantity"), body: _t("Use Refund to return an add-on.") };
        }
        const limit = this.order_id?.config.ne_addon_limit;
        if (this.ne_parent_uuid && limit && Number(quantity) > 0) {
            const others = this.neGetParent()?.neGetAddons().filter((line) => line !== this &&
                line.uuid !== this.uiState.neMergingUuid && line.product_id === this.product_id) || [];
            if (Number(quantity) + others.reduce((sum, line) => sum + line.qty, 0) > limit) {
                return { title: _t("Add-on limit"), body: _t("The maximum quantity for this add-on is %s.", limit) };
            }
        }
        const result = super.setQuantity(...arguments);
        const source = this.refunded_orderline_id;
        if (result === true && source?.qty && source.getFixedDiscountAmount?.()) {
            this.setFixedDiscountAmount?.(source.getFixedDiscountAmount() * Math.abs(this.qty / source.qty));
        }
        return result;
    },
    setDiscount(discount) {
        super.setDiscount(...arguments);
        for (const addon of this.neGetAddons()) addon.setDiscount(this.discount);
    },
    getFullProductName() {
        const name = super.getFullProductName(...arguments);
        const parent = this.neGetParent();
        const label = parent?.full_product_name || this.ne_parent_label;
        return label ? `${name} (${label})` : name;
    },
});

patch(PosOrder.prototype, {
    removeOrderline(line) {
        const result = super.removeOrderline(...arguments);
        const selected = this.getSelectedOrderline();
        if (selected?.neGetParent()) this.selectOrderline(selected.neGetParent());
        return result;
    },
});
