import { roundPrecision } from "@web/core/utils/numbers";

/** Currency-unit allocation, mirrored in models/discount_math.py. */
export function allocateDiscount(grosses, type, input, rounding) {
    const units = grosses.map((gross) => Math.max(0, Math.round(roundPrecision(gross, rounding) / rounding)));
    const base = units.reduce((sum, value) => sum + value, 0);
    const value = Number.isFinite(input) ? Math.max(0, input) : 0;
    const target = type === "percent"
        ? roundPrecision(base * Math.min(value, 100) / 100, 1)
        : type === "fixed" ? Math.min(base, Math.round(roundPrecision(value, rounding) / rounding)) : 0;
    if (!base || !target) return units.map(() => 0);
    const allocations = units.map((unit) => Math.floor(target * unit / base));
    const ranked = units.map((unit, index) => ({ index, remainder: (target * unit) % base }))
        .sort((a, b) => b.remainder - a.remainder || a.index - b.index);
    const residual = target - allocations.reduce((sum, value) => sum + value, 0);
    for (let i = 0; i < residual; i++) allocations[ranked[i].index]++;
    return allocations.map((unit) => unit * rounding);
}

/** Cumulative rounding makes the final partial return reverse the last cent. */
export function refundShare(amount, sourceQty, returnedQty, previousQty, round) {
    if (!sourceQty) return 0;
    const before = Math.min(Math.abs(sourceQty), Math.max(0, previousQty));
    const after = Math.min(Math.abs(sourceQty), before + Math.abs(returnedQty));
    return round(round(amount * after / Math.abs(sourceQty)) -
        round(amount * before / Math.abs(sourceQty)));
}

/** Invert the real Odoo engine, then reconstruct its native included/excluded price. */
export function priceForGross(baseLine, target, engine) {
    const factor = 1 - baseLine.discount / 100;
    if (!baseLine.quantity || !factor) return baseLine.price_unit;
    const options = { rounding_method: "round_globally", product: baseLine.product_id,
        product_uom: baseLine.product_uom_id };
    const details = engine.get_tax_details(baseLine.tax_ids, target / baseLine.quantity,
        baseLine.quantity, { ...options, special_mode: "total_included" });
    const included = details.taxes_data.filter((entry) => entry.tax.price_include)
        .reduce((sum, entry) => sum + entry.tax_amount, 0);
    const price = (details.total_excluded + included) / (baseLine.quantity * factor);
    const check = engine.get_tax_details(baseLine.tax_ids, price * factor, baseLine.quantity, options);
    if (!Number.isFinite(price) || Math.abs(check.total_included - target) > 0.000001) {
        throw new Error("The configured taxes cannot reconcile this discount. Check the tax configuration.");
    }
    return price;
}
