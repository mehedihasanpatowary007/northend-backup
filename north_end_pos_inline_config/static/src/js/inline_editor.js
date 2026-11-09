import { Component, useEffect, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { formatCurrency } from "@web/core/currency";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import {
    inlineEligible, attributeLines, attributeValues, selectedValues, validCombination,
    defaultValues, configurationPayload, refreshOrder, mergeIntoOrder, ensureVariantData,
} from "./configuration";

export class InlineEditor extends Component {
    static template = "north_end_pos_inline_config.InlineEditor";
    static props = {};

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.numberBuffer = useService("number_buffer");
        this.state = useState({ busy: false, refreshing: false });
        useEffect(() => {
            const template = this.line?.product_id.product_tmpl_id;
            if (!template) {
                this.state.refreshing = false;
                return;
            }
            let active = true;
            this.state.refreshing = true;
            ensureVariantData(this.pos, template).catch((error) => {
                if (active) {
                    this.dialog.add(AlertDialog, { title: _t("Cannot load item options"), body: error.message });
                }
            }).finally(() => {
                if (active) this.state.refreshing = false;
            });
            return () => { active = false; };
        }, () => [this.line?.product_id.product_tmpl_id.id]);
    }
    get isBusy() {
        return this.state.busy || this.state.refreshing;
    }
    get line() {
        const selected = this.pos.getOrder()?.getSelectedOrderline();
        const line = selected?.neGetParent() || selected;
        return line && inlineEligible(this.pos, line.product_id.product_tmpl_id) &&
            line.qty > 0 && !line.is_reward_line && !line.refunded_orderline_id && !line.isPartOfCombo() ? line : null;
    }
    get attributes() {
        return this.line ? attributeLines(this.line.product_id.product_tmpl_id) : [];
    }
    valuesForAttribute(attribute) {
        return attributeValues(attribute);
    }
    get addonRows() {
        if (!this.line) return [];
        return this.line.product_id.product_tmpl_id.pos_optional_product_ids
            // The explicit Optional Products relation is sufficient POS
            // availability: Odoo loads these linked templates with the menu.
            .filter((template) => template.active !== false && template.sale_ok && !template.isCombo())
            .flatMap((template) => {
                const variants = template.product_variant_ids.filter((variant) => variant.active !== false);
                return (variants.length ? variants : [null]).map((product) => ({
                    key: `${template.id}-${product?.id || "dynamic"}`,
                    template, product,
                    name: product?.display_name || template.name,
                }));
            });
    }
    get visible() {
        return this.line && (this.attributes.length || this.addonRows.length);
    }
    isSelected(value) {
        return selectedValues(this.line).some((selected) => selected.id === value.id);
    }
    valuesFor(value) {
        const current = selectedValues(this.line);
        if (value.attribute_id.display_type === "multi") {
            return this.isSelected(value) ? current.filter((item) => item.id !== value.id) : [...current, value];
        }
        return [...current.filter((item) => item.attribute_id.id !== value.attribute_id.id), value];
    }
    isAvailable(value) {
        return validCombination(this.line.product_id.product_tmpl_id, this.valuesFor(value), this.pos);
    }
    customValue(value) {
        return this.line.custom_attribute_value_ids.find((item) =>
            item.custom_product_template_attribute_value_id.id === value.id)?.custom_value || "";
    }
    amount(value) {
        return formatCurrency(value, this.pos.currency.id);
    }
    matchingAddons(row, parent = this.line) {
        return parent.neGetAddons().filter((line) => row.product ? line.product_id === row.product :
            line.product_id.product_tmpl_id === row.template);
    }
    sameAddonSale(left, right) {
        const ids = (records) => records.map((record) => record.id).sort((a, b) => a - b).join(",");
        return left.ne_parent_uuid === right.ne_parent_uuid && left.product_id === right.product_id &&
            left.price_type === right.price_type && left.discount === right.discount &&
            left.note === right.note && left.customer_note === right.customer_note &&
            !(left.getFixedDiscountAmount?.() || 0) && !(right.getFixedDiscountAmount?.() || 0) &&
            !left.refunded_orderline_id && !right.refunded_orderline_id &&
            !left.is_reward_line && !right.is_reward_line && !left.isPartOfCombo() && !right.isPartOfCombo() &&
            left.product_id.tracking === "none" && right.product_id.tracking === "none" &&
            !left.pack_lot_ids.length && !right.pack_lot_ids.length &&
            ids(left.tax_ids) === ids(right.tax_ids) && ids(left.attribute_value_ids) === ids(right.attribute_value_ids) &&
            JSON.stringify(left.custom_attribute_value_ids.map((item) => [
                item.custom_product_template_attribute_value_id.id, item.custom_value,
            ]).sort()) === JSON.stringify(right.custom_attribute_value_ids.map((item) => [
                item.custom_product_template_attribute_value_id.id, item.custom_value,
            ]).sort()) && (left.price_type === "original" || left.currency.isZero(left.price_unit - right.price_unit));
    }
    normalizeAddons(lines) {
        const remaining = [...lines];
        while (remaining.length) {
            const target = remaining.shift();
            const duplicates = remaining.filter((line) => this.sameAddonSale(target, line));
            for (const line of duplicates) remaining.splice(remaining.indexOf(line), 1);
            if (!duplicates.length) continue;
            for (const line of duplicates) {
                target.merge(line);
                line.delete();
            }
        }
    }
    addonQty(row) {
        return this.matchingAddons(row).reduce((sum, line) => sum + line.qty, 0);
    }
    atLimit(row) {
        return this.pos.config.ne_addon_limit > 0 && this.addonQty(row) >= this.pos.config.ne_addon_limit;
    }
    addonPrice(row) {
        const line = this.matchingAddons(row)[0];
        if (line) return line.currencyDisplayPriceUnit;
        const product = row.product || row.template;
        const priceExtra = attributeLines(row.template).filter((line) =>
            line.attribute_id.create_variant === "no_variant" && line.attribute_id.display_type !== "multi")
            .reduce((sum, line) => sum + (attributeValues(line)[0]?.price_extra || 0), 0);
        const details = product.getTaxDetails({ overridedValues: {
            pricelist: this.line.order_id.pricelist_id,
            fiscalPosition: this.line.order_id.fiscal_position_id,
            priceExtra,
            discount: this.line.discount,
        } });
        return this.amount(this.pos.config.iface_tax_included === "total" ? details.total_included : details.total_excluded);
    }
    async run(action) {
        if (this.isBusy || !this.line) return;
        const line = this.line;
        const order = line.order_id;
        this.state.busy = true;
        this.numberBuffer.reset();
        try {
            order.assertEditable();
            await action(line);
            refreshOrder(this.pos, order);
        } catch (error) {
            this.dialog.add(AlertDialog, { title: _t("Cannot update item"), body: error.message });
        } finally {
            this.state.busy = false;
        }
    }
    async changeAttribute(value, customValue) {
        const values = customValue === undefined ? this.valuesFor(value) : selectedValues(this.line);
        if (customValue === undefined && this.isSelected(value) && value.attribute_id.display_type !== "multi") return;
        return this.run(async (line) => {
            if (this.pos.disallowLineQuantityChange()) {
                throw new Error(_t("Your POS quantity permissions do not allow changing this item's variant here."));
            }
            const template = line.product_id.product_tmpl_id;
            if (!validCombination(template, values, this.pos)) throw new Error(_t("This combination is unavailable."));
            // Follow the core configurator restriction once an item has reached preparation.
            let preparation = line.order_id.last_order_preparation_change;
            if (typeof line.order_id.id === "number") {
                const data = await this.pos.data.call("pos.order", "get_preparation_change", [line.order_id.id]);
                preparation = JSON.parse(data.last_order_preparation_change || "{}");
            }
            if (Object.values(preparation?.lines || {}).some((item) => item.uuid === line.uuid) ||
                preparation?.lines?.[line.preparationKey]) {
                throw new Error(_t("This item has already been sent to the kitchen. Remove it and add the required variant."));
            }
            const order = line.order_id;
            const payload = configurationPayload(values, line);
            if (customValue !== undefined) payload.attribute_custom_values[value.id] = customValue;
            const quantity = Math.min(1, line.qty);
            const fixed = line.getFixedDiscountAmount?.() || 0;
            const movedDiscount = fixed * quantity / line.qty;
            const originalQuantity = line.qty;
            const originalPrice = line.price_unit;
            const originalDiscount = line.discount;
            const vals = {
                product_tmpl_id: template, payload, qty: quantity,
                discount: line.discount, note: line.note, customer_note: line.customer_note,
                tax_ids: line.tax_ids.map((tax) => ["link", tax]),
            };
            if (line.price_type !== "original") {
                vals.price_unit = line.price_unit;
                vals.price_type = line.price_type;
            }
            const next = await this.pos.addLineToOrder(vals, order, { merge: false });
            if (!next) return;
            if (next.price_unit < 0) {
                next.delete();
                order.selectOrderline(line);
                throw new Error(_t("The variant price cannot be negative."));
            }
            // Do not mutate the source until native product configuration has succeeded.
            if (!order.lines.includes(line)) {
                next.delete();
                return;
            }
            if (line.qty !== originalQuantity || line.price_unit !== originalPrice ||
                line.discount !== originalDiscount || (line.getFixedDiscountAmount?.() || 0) !== fixed) {
                next.delete();
                order.selectOrderline(line);
                throw new Error(_t("The item changed while the variant was loading. Please select the option again."));
            }
            if (line.qty > quantity) {
                const result = line.setQuantity(line.qty - quantity);
                if (result !== true) {
                    next.delete();
                    throw new Error(result.body);
                }
                line.setFixedDiscountAmount?.(fixed - movedDiscount);
            } else {
                for (const addon of line.neGetAddons()) {
                    addon.update({ ne_parent_uuid: next.uuid, ne_parent_label: next.full_product_name });
                }
                line.delete();
            }
            next.setFixedDiscountAmount?.(movedDiscount);
            order.selectOrderline(mergeIntoOrder(next));
        });
    }
    async changeAddon(row, delta) {
        return this.run(async (parent) => {
            const order = parent.order_id;
            const existing = this.matchingAddons(row, parent);
            if (delta < 0) {
                if (this.pos.disallowLineQuantityChange()) {
                    throw new Error(_t("Your POS quantity permissions do not allow removing add-ons here."));
                }
                const line = existing.at(-1);
                if (!line) return;
                if (line.qty <= 1) order.removeOrderline(line);
                else {
                    const result = line.setQuantity(line.qty - 1);
                    if (result !== true) throw new Error(result.body);
                }
            } else {
                if (this.atLimit(row)) return;
                await ensureVariantData(this.pos, row.template);
                const values = defaultValues(row.template, row.product?.product_template_attribute_value_ids || [], Boolean(row.product), this.pos);
                const line = await this.pos.addLineToOrder({
                    product_tmpl_id: row.template,
                    ...(inlineEligible(this.pos, row.template) ? { payload: configurationPayload(values) } : {}),
                    ...(row.product ? { product_id: row.product } : {}),
                    discount: parent.discount,
                    ne_parent_uuid: parent.uuid, ne_parent_label: parent.full_product_name,
                }, order, { merge: false, ...(row.product ? { presetVariant: row.product } : {}) });
                if (line && (!order.lines.includes(parent) || line.price_unit < 0)) {
                    order.removeOrderline(line);
                    throw new Error(_t("The add-on could not be added. Check its price and parent item."));
                }
                if (line) {
                    const target = existing.find((candidate) => this.sameAddonSale(candidate, line));
                    if (target) {
                        target.merge(line);
                        line.delete();
                    } else {
                        mergeIntoOrder(line);
                    }
                    this.normalizeAddons(this.matchingAddons(row, parent));
                }
            }
            if (order.lines.includes(parent)) order.selectOrderline(parent);
        });
    }
}
