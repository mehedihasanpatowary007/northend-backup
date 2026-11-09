import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError } from "@web/core/network/rpc";

const variantDataLoads = new WeakMap();

export async function ensureVariantData(pos, template) {
    if (!template.attribute_line_ids.length) return true;
    let loads = variantDataLoads.get(pos);
    if (!loads) {
        loads = new Map();
        variantDataLoads.set(pos, loads);
    }
    if (!loads.has(template.id)) {
        // Refresh through the native related-record loader, including variants,
        // current attribute values, and exclusions. Deduplicate rapid taps.
        const loading = (async () => {
            try {
                await pos.loadNewProducts([["id", "=", template.id]]);
                return true;
            } catch (error) {
                loads.delete(template.id);
                // Existing offline combinations remain usable. Retry the
                // refresh next time rather than treating an offline cache as current.
                if (error instanceof ConnectionLostError) return false;
                throw error;
            }
        })();
        loads.set(template.id, loading);
    }
    return loads.get(template.id);
}

export function inlineEligible(pos, template) {
    return Boolean(
        pos.config.ne_inline_enabled && template && !template.isCombo() &&
        !template.to_weight && template.tracking === "none"
    );
}

export function attributeLines(template) {
    return template.attribute_line_ids.filter((line) => line.active !== false && attributeValues(line).length);
}

export function attributeValues(line) {
    return line.values().filter((value) => value.ptav_active !== false);
}

export function selectedValues(line) {
    const available = new Map(attributeLines(line.product_id.product_tmpl_id)
        .flatMap(attributeValues).map((value) => [value.id, value]));
    const productValues = line.product_id.product_template_attribute_value_ids
        .map((value) => available.get(value.id)).filter(Boolean);
    const values = new Map();
    // The real SKU controls variant-generating choices and its price/MO.
    // Explicit line choices control modifiers that do not create a variant.
    const storedValues = [
        ...productValues.filter((value) => value.attribute_id.create_variant === "no_variant"),
        ...line.attribute_value_ids,
        ...productValues.filter((value) => value.attribute_id.create_variant !== "no_variant"),
    ];
    for (const stored of storedValues) {
        const value = available.get(stored.id);
        if (!value) continue;
        const key = value.attribute_id.display_type === "multi" ? `value:${value.id}` : `attribute:${value.attribute_id.id}`;
        values.set(key, value);
    }
    return [...values.values()];
}

export function validCombination(template, values, pos) {
    if (values.some((value) => value.ptav_active === false)) return false;
    if (pos?.productAttributesExclusion && values.some((value) => pos.doHaveConflictWith(value, values))) {
        return false;
    }
    const variantIds = values.filter((value) => value.attribute_id.create_variant !== "no_variant").map((value) => value.id);
    const ids = new Set(variantIds);
    // An old archived variant containing only Size must not disable every
    // current Size + Brand variant. Actual pair exclusions are checked above.
    if ((template._archived_combinations || []).some((combination) =>
        combination.length > 0 && combination.length === ids.size && combination.every((id) => ids.has(id)))) {
        return false;
    }
    const dynamic = attributeLines(template).some((line) => line.attribute_id.create_variant === "dynamic");
    return dynamic || !variantIds.length || template.product_variant_ids.some((variant) =>
        variant.active !== false && variantIds.every((id) =>
            variant.product_template_attribute_value_ids.some((v) => v.id === id)));
}

export function defaultValues(template, preferred = [], exactVariant = false, pos) {
    const lines = attributeLines(template).filter((line) => line.attribute_id.display_type !== "multi");
    // Search in attribute sequence order, preferring the currently selected variant.
    const visit = (index, selected) => {
        if (index === lines.length) {
            return validCombination(template, selected, pos) ? selected : null;
        }
        const values = attributeValues(lines[index]).filter((value) => !exactVariant ||
            value.attribute_id.create_variant === "no_variant" ||
            !preferred.some((item) => item.attribute_id.id === value.attribute_id.id) ||
            preferred.some((item) => item.id === value.id)).sort((a, b) =>
            Number(preferred.some((v) => v.id === b.id)) - Number(preferred.some((v) => v.id === a.id)));
        for (const value of values) {
            const result = visit(index + 1, [...selected, value]);
            if (result) return result;
        }
        return null;
    };
    const result = visit(0, []);
    if (!result) throw new Error(_t("No available variant combination for this product."));
    return result;
}

export function configurationPayload(values, line) {
    const custom = {};
    for (const item of line?.custom_attribute_value_ids || []) {
        custom[item.custom_product_template_attribute_value_id.id] = item.custom_value;
    }
    return {
        attribute_value_ids: values.map((value) => value.id),
        attribute_custom_values: Object.fromEntries(values.filter((value) => value.is_custom)
            .map((value) => [value.id, custom[value.id] || ""])),
        price_extra: values.filter((value) => value.attribute_id.create_variant === "no_variant")
            .reduce((sum, value) => sum + value.price_extra, 0),
    };
}

export function refreshOrder(pos, order) {
    order.triggerRecomputeAllPrices?.();
    pos.updateRewards?.();
}

export function compatibleSaleLines(left, right) {
    const ids = (records) => records.map((record) => record.id).sort((a, b) => a - b).join(",");
    const custom = (records) => records.map((item) => [
        item.custom_product_template_attribute_value_id.id, item.custom_value,
    ]).sort((a, b) => a[0] - b[0]);
    const fixedLeft = left.getFixedDiscountAmount?.() || 0;
    const fixedRight = right.getFixedDiscountAmount?.() || 0;
    return left !== right && left.product_id === right.product_id &&
        (left.ne_parent_uuid || false) === (right.ne_parent_uuid || false) &&
        left.price_type === right.price_type && left.discount === right.discount &&
        left.note === right.note && left.customer_note === right.customer_note &&
        left.qty > 0 && right.qty > 0 && !left.refunded_orderline_id && !right.refunded_orderline_id &&
        !left.is_reward_line && !right.is_reward_line &&
        !left.combo_parent_id && !right.combo_parent_id && !left.isPartOfCombo() && !right.isPartOfCombo() &&
        left.product_id.tracking === "none" && right.product_id.tracking === "none" &&
        !left.pack_lot_ids.length && !right.pack_lot_ids.length && !fixedLeft && !fixedRight &&
        ids(left.tax_ids) === ids(right.tax_ids) &&
        ids(left.attribute_value_ids) === ids(right.attribute_value_ids) &&
        JSON.stringify(custom(left.custom_attribute_value_ids)) === JSON.stringify(custom(right.custom_attribute_value_ids)) &&
        (left.price_type === "original" || left.currency.isZero(left.price_unit - right.price_unit));
}

export function mergeIntoOrder(line) {
    const limit = line.order_id.config.ne_addon_limit;
    const target = line.order_id.lines.find((other) => {
        if (!compatibleSaleLines(other, line)) return false;
        if (!limit) return true;
        const totals = new Map();
        for (const addon of [...other.neGetAddons(), ...line.neGetAddons()]) {
            totals.set(addon.product_id.id, (totals.get(addon.product_id.id) || 0) + addon.qty);
        }
        return [...totals.values()].every((qty) => qty <= limit);
    });
    if (target) {
        target.merge(line);
        for (const addon of target.neGetAddons()) {
            for (const duplicate of target.neGetAddons().filter((other) => other !== addon && compatibleSaleLines(addon, other))) {
                addon.merge(duplicate);
                duplicate.delete();
            }
        }
        line.delete();
        return target;
    }
    return line;
}
