import { Component } from "@odoo/owl";
import { formatCurrency } from "@web/core/currency";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";

const { DateTime } = luxon;

export class SettlementReceipt extends Component {
    static template = "pos_settlement_bill.SettlementReceipt";
    static props = { data: Object };
}

/** Read an order into a plain receipt snapshot without validating or changing it. */
export function buildSettlementReceipt(pos, order, authorization = {}) {
    const config = order.config;
    const company = order.company;
    const currency = order.currency;
    const money = (amount) => formatCurrency(amount, currency.id);
    // These getters include the installed discount/fiscal-position extensions.
    // Never recompute tax, discounts, or payment-method rounding in the receipt.
    const taxDetails = order.prices.taxDetails;
    const amountDue = order.totalDue;
    if (![order.priceExcl, order.priceIncl, amountDue].every(Number.isFinite)) {
        throw new Error(_t("Order totals are not ready. Please try again."));
    }
    const globalDiscount = order.neGlobalDiscountAmount || 0;
    const rounding = currency.round(amountDue - order.priceIncl);
    const sortedLines = order.lines.reduce((lines, line) => {
        if (line.combo_line_ids?.length) {
            lines.push(line, ...line.combo_line_ids);
        } else if (!line.combo_parent_id) {
            lines.push(line);
        }
        return lines;
    }, []);
    const lines = sortedLines.map((line) => {
        const quantity = line.getQuantityStr().qtyStr;
        const discounts = [];
        if (line.getDiscount() && !line.combo_parent_id) {
            discounts.push(_t("Line discount: %s%%", line.getDiscountStr()));
        }
        if (line.fixedDiscountAmount && !line.combo_parent_id) {
            discounts.push(_t("Fixed discount: %s", line.fixedDiscountAmount));
        }
        return {
            key: line.uuid,
            name: line.getFullProductName(),
            quantity,
            // Odoo's display getters preserve the cart's pre-order-discount
            // presentation; the explicit order-discount section below reconciles it.
            unitPrice: line.combo_parent_id ? "" : line.currencyDisplayPriceUnit,
            amount: line.combo_parent_id ? "" : line.currencyDisplayPrice,
            isComboChild: Boolean(line.combo_parent_id),
            discounts,
            customerNote: line.getCustomerNote(),
        };
    });
    const taxRows = (taxDetails.subtotals || []).flatMap((subtotal, subtotalIndex) =>
        (subtotal.tax_groups || []).map((group, index) => ({
            key: `${subtotalIndex}:${group.id ?? index}`,
            name: group.group_name || _t("Tax"),
            amount: money(group.tax_amount_currency),
            base: taxDetails.same_tax_base ? "" : money(group.base_amount_currency),
        }))
    );
    if (!taxRows.length && !currency.isZero(order.amountTaxes)) {
        taxRows.push({ key: "tax", name: _t("Taxes"), amount: money(order.amountTaxes), base: "" });
    }
    const table = order.table_id;
    const partner = order.getPartner();
    const cashier = pos.getCashier?.() || pos.cashier;
    const printedAt = authorization.printed_at
        ? deserializeDateTime(authorization.printed_at)
        : DateTime.now();
    const address = [company.street, company.street2,
        [company.city, company.state_id?.name, company.zip].filter(Boolean).join(", ")]
        .filter(Boolean);
    const reference = order.pos_reference || (order.name !== "/" && order.name)
        || order.tracking_number || order.uuid.slice(0, 8);
    return {
        orderUuid: order.uuid,
        orderReference: String(reference),
        companyName: company.name,
        logoUrl: config.receiptLogoUrl || "",
        address,
        phone: company.phone || "",
        email: company.email || "",
        website: company.website || "",
        taxId: company.vat || "",
        registerName: config.name,
        receiptHeader: config.receipt_header || "",
        customer: partner?.name || "",
        table: table ? String(table.table_number ?? table.name ?? "") : "",
        floor: table?.floor_id?.name || "",
        guests: table && order.customer_count ? String(order.customer_count) : "",
        orderLabel: order.floating_order_name || "",
        cashier: cashier?.name || order.getCashierName?.() || "",
        authorizedBy: authorization.employee_name || "",
        orderedAt: order.date_order ? order.formatDateOrTime("date_order") : "",
        printedAt: formatDateTime(printedAt),
        lines,
        itemPriceLabel: config.iface_tax_included === "total"
            ? _t("Item prices include tax") : _t("Item prices exclude tax"),
        globalDiscount: globalDiscount ? money(-globalDiscount) : "",
        globalDiscountLabel: globalDiscount ? order.neGlobalDiscountLabel : "",
        itemsBeforeGlobal: globalDiscount ? money(order.neGrossBeforeGlobal) : "",
        subtotal: money(order.priceExcl),
        taxRows,
        rounding: currency.isZero(rounding) ? "" : money(rounding),
        amountDue: money(amountDue),
        cashRoundingNote: Boolean(config.cash_rounding && config.only_round_cash_method),
        customerNote: order.general_customer_note || "",
        receiptFooter: config.receipt_footer || "",
    };
}
