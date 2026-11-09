import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { CategorySelector } from "@point_of_sale/app/components/category_selector/category_selector";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { InlineEditor } from "./inline_editor";
import { inlineEligible, defaultValues, configurationPayload, refreshOrder, mergeIntoOrder, selectedValues, ensureVariantData } from "./configuration";

const HEX_COLOR_OFFSET = 0x1000000;

class VerticalCategories extends CategorySelector {
    static template = "north_end_pos_inline_config.VerticalCategories";
    categoryPath(id) {
        const category = this.pos.models["pos.category"].get(id);
        return [...category.allParents, category].map((item) => item.name).join(" / ");
    }
}

patch(CategorySelector.prototype, {
    posCategoryColorStyle(category) {
        const encodedColor = Number(category.color);
        if (encodedColor < HEX_COLOR_OFFSET || encodedColor > HEX_COLOR_OFFSET + 0xffffff) {
            return {};
        }
        const hex = `#${(encodedColor - HEX_COLOR_OFFSET).toString(16).padStart(6, "0")}`;
        const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16));
        const luminance = (0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]) / 255;
        const textColor = luminance > 0.55 ? "#212529" : "#ffffff";
        return `background-color: ${hex} !important; border-color: ${hex} !important; color: ${textColor} !important;`;
    },
});

patch(ProductScreen, { components: { ...ProductScreen.components, InlineEditor, VerticalCategories } });
patch(ProductScreen.prototype, {
    async addProductToOrder(product) {
        if (!inlineEligible(this.pos, product) || this.currentOrder?.isRefund) {
            return super.addProductToOrder(...arguments);
        }
        // Serialize rapid taps; retain every tap while dynamic variants are loading.
        const previous = this._neAddQueue || Promise.resolve();
        const operation = previous.catch(() => {}).then(async () => {
            const order = this.pos.getOrder();
            order?.assertEditable();
            await ensureVariantData(this.pos, product);
            if (this.pos.getOrder() !== order) return;
            order?.assertEditable();
            this.numberBuffer.reset();
            const selectedLine = order?.getSelectedOrderline();
            const selected = selectedLine?.neGetParent() || selectedLine;
            const searchedVariant = this.searchWord && product.product_variant_ids.find((variant) =>
                variant.barcode === this.searchWord || variant.default_code === this.searchWord);
            const useSelectedVariant = selected && selected.product_id.product_tmpl_id === product &&
                !selected.ne_parent_uuid && !selected.is_reward_line && selected.qty > 0 &&
                (!searchedVariant || searchedVariant === selected.product_id);
            const preferred = searchedVariant?.product_template_attribute_value_ids ||
                (useSelectedVariant ? selectedValues(selected) : []);
            const values = defaultValues(product, preferred, Boolean(searchedVariant || useSelectedVariant), this.pos);
            const payload = configurationPayload(values, useSelectedVariant ? selected : undefined);
            if (useSelectedVariant && selected.price_type === "original" && !selected.discount &&
                !selected.note && !selected.customer_note && !(selected.getFixedDiscountAmount?.() || 0) &&
                !selected.refunded_orderline_id && !selected.isPartOfCombo()) {
                const result = selected.setQuantity(selected.qty + 1);
                if (result !== true) {
                    this.dialog.add(AlertDialog, result);
                    return selected;
                }
                refreshOrder(this.pos, order);
                order.selectOrderline(selected);
                return selected;
            }
            const desiredVariantIds = new Set(values.filter((value) => value.attribute_id.create_variant !== "no_variant").map((value) => value.id));
            const candidate = (useSelectedVariant ? [selected, ...order.lines] : order.lines).find((line) =>
                !line.ne_parent_uuid && !line.refunded_orderline_id && !line.is_reward_line &&
                line.product_id.product_tmpl_id === product && line.qty > 0 &&
                line.product_id.product_template_attribute_value_ids.filter((value) =>
                    value.attribute_id.create_variant !== "no_variant").map((value) => value.id).every((id) => desiredVariantIds.has(id)) &&
                [...desiredVariantIds].every((id) => line.product_id.product_template_attribute_value_ids.some((value) => value.id === id)) &&
                JSON.stringify(line.attribute_value_ids.map((value) => value.id).sort()) === JSON.stringify(payload.attribute_value_ids.sort()) &&
                JSON.stringify(Object.fromEntries(line.custom_attribute_value_ids.map((item) => [
                    item.custom_product_template_attribute_value_id.id, item.custom_value,
                ]).sort())) === JSON.stringify(payload.attribute_custom_values) &&
                line.price_type === "original" && !line.discount && !line.note && !line.customer_note &&
                !(line.getFixedDiscountAmount?.() || 0) && !line.isPartOfCombo());
            if (candidate) {
                const result = candidate.setQuantity(candidate.qty + 1);
                if (result !== true) this.dialog.add(AlertDialog, result);
                refreshOrder(this.pos, order);
                order.selectOrderline(candidate);
                return candidate;
            }
            const line = await this.pos.addLineToCurrentOrder({
                product_tmpl_id: product,
                payload,
            }, { merge: false });
            if (line && line.price_unit < 0) {
                line.order_id.removeOrderline(line);
                throw new Error(_t("The product price cannot be negative."));
            }
            if (line) {
                const merged = mergeIntoOrder(line);
                merged.order_id.selectOrderline(merged);
                return merged;
            }
        });
        this._neAddQueue = operation;
        try {
            return await operation;
        } catch (error) {
            this.dialog.add(AlertDialog, { title: _t("Cannot add product"), body: error.message });
        }
    },
});

patch(OrderSummary.prototype, {
    _setValue(value) {
        const line = this.currentOrder.getSelectedOrderline();
        if (line && inlineEligible(this.pos, line.product_id.product_tmpl_id) &&
            !line.refunded_orderline_id && !line.is_reward_line && value !== "remove" &&
            this.pos.numpadMode === "quantity" && Number(value) <= 0) {
            if (Number(value) === 0) {
                this.currentOrder.removeOrderline(line);
                refreshOrder(this.pos, this.currentOrder);
            } else {
                this.dialog.add(AlertDialog, { title: _t("Invalid quantity"), body: _t("Use Refund to return a sold item.") });
            }
            this.numberBuffer.reset();
            return;
        }
        return super._setValue(...arguments);
    },
    async setLinePrice(line, price) {
        if (this.pos.config.ne_inline_enabled && Number(price) < 0 && !line.is_reward_line) {
            this.numberBuffer.reset();
            this.dialog.add(AlertDialog, { title: _t("Invalid price"), body: _t("The item price cannot be negative.") });
            return;
        }
        return super.setLinePrice(...arguments);
    },
    async onOrderlineLongPress(ev, line) {
        if (inlineEligible(this.pos, line.product_id.product_tmpl_id) && !line.is_reward_line && line.qty > 0) {
            ev.stopPropagation();
            this.numberBuffer.reset();
            this.pos.selectOrderLine(this.currentOrder, line);
            if (this.pos.isSmallProductScreen) this.pos.mobile_pane = "right";
            return;
        }
        return super.onOrderlineLongPress(...arguments);
    },
});
