/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

const pad = (value) => String(value).padStart(2, "0");
const iso = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const DEFAULT_CURRENCY = "\u09F3";
const PAYMENT_COLORS = ["#75432c", "#c9893b", "#2e8374", "#4d6fb3", "#c75a5a", "#9d9285"];
const CATEGORY_COLORS = ["#75432c", "#c9893b", "#2e8374", "#4d6fb3", "#c75a5a", "#9d9285"];
const HEAT_COLORS = ["#eeeae6", "#d8c9bd", "#bba89b", "#9c7e6c", "#75432c"];

function orderDate(order) {
    const value = order.timestamp || `${order.date || ""}T00:00:00`;
    const date = new Date(value.replace(" ", "T"));
    return Number.isNaN(date.getTime()) ? null : date;
}

function periodLabel(from, to) {
    const start = new Date(`${from}T00:00:00`);
    const end = new Date(`${to}T00:00:00`);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "Custom range";
    const month = new Intl.DateTimeFormat("en", { month: "short" });
    const year = end.getFullYear();
    return `${pad(start.getDate())}–${pad(end.getDate())} ${month.format(end)} ${year}`;
}

export class PosSalesDashboard extends Component {
    static template = "zencore_pos_dashboard.PosSalesDashboard";

    setup() {
        const now = new Date();
        this.state = useState({
            orders: [], previous: [], filtered: [], previousFiltered: [], targets: { outlets: [], officers: [] }, loading: true, error: "",
            currency: DEFAULT_CURRENCY, syncedAt: null, period: "month", compare: "previous",
            dateFrom: iso(new Date(now.getFullYear(), now.getMonth(), 1)), dateTo: iso(now),
            register: "", employee: "", category: "", payment: "", gran: "day", tip: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            const data = await rpc("/pos_dashboard/data", { date_from: this.state.dateFrom, date_to: this.state.dateTo });
            this.state.currency = data.currency || DEFAULT_CURRENCY;
            this.state.orders = (data.orders || []).filter((order) => order.period === "current");
            this.state.previous = (data.orders || []).filter((order) => order.period === "previous");
            this.state.targets = data.targets || { outlets: [], officers: [] };
            this.state.syncedAt = new Date();
            this.state.error = "";
            this.applyFilters();
        } catch (error) {
            this.state.error = error?.message || "Unable to load POS sales.";
            this.state.orders = [];
            this.state.previous = [];
            this.state.targets = { outlets: [], officers: [] };
            this.applyFilters();
        } finally {
            this.state.loading = false;
        }
    }

    applyFilters() {
        const filter = (rows) => rows.filter((order) => (
            (!this.state.register || order.register === this.state.register)
            && (!this.state.employee || order.employee === this.state.employee)
            && (!this.state.payment || (order.payment_names || []).includes(this.state.payment))
            && (!this.state.category || (order.lines || []).some((line) => line.category === this.state.category))
        ));
        this.state.filtered = filter(this.state.orders);
        this.state.previousFiltered = filter(this.state.previous);
    }

    money(value) {
        return `${this.state.currency || DEFAULT_CURRENCY}\u00A0${Math.round(Number(value || 0)).toLocaleString("en-US")}`;
    }

    thousand(value) {
        return `${this.state.currency || DEFAULT_CURRENCY}\u00A0${(Number(value || 0) / 1000).toFixed(1)} K`;
    }

    stats(rows) {
        const positive = rows.filter((order) => Number(order.amount) >= 0);
        const refunds = rows.filter((order) => Number(order.amount) < 0);
        const gross = positive.reduce((sum, order) => sum + Number(order.amount || 0), 0);
        const refund = Math.abs(refunds.reduce((sum, order) => sum + Number(order.amount || 0), 0));
        const items = positive.reduce((sum, order) => sum + (order.lines || []).reduce((lineSum, line) => lineSum + Math.max(0, Number(line.qty || 0)), 0), 0);
        const discounts = positive.reduce((sum, order) => sum + Number(order.discount || 0), 0);
        return { gross, net: gross - refund, refunds: refund, orders: positive.length, items, discounts, aov: positive.length ? gross / positive.length : 0, refundCount: refunds.length };
    }

    get current() { return this.stats(this.state.filtered); }
    get previousStats() { return this.stats(this.state.previousFiltered); }
    get syncTime() { return (this.state.syncedAt || new Date()).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
    get dateLabel() { return periodLabel(this.state.dateFrom, this.state.dateTo); }
    get outlets() { return [...new Set(this.state.orders.map((order) => order.register))].filter(Boolean).sort(); }
    get employees() { return [...new Set(this.state.orders.map((order) => order.employee))].filter(Boolean).sort(); }
    get categories() { return [...new Set(this.state.orders.flatMap((order) => (order.lines || []).map((line) => line.category)))].filter(Boolean).sort(); }
    get payments() { return [...new Set(this.state.orders.flatMap((order) => order.payment_names || [order.payment]))].filter(Boolean).sort(); }

    growth(current, previous, inverse = false) {
        if (!previous) return { text: current ? "New" : "N/A", cls: "neutral", arrow: "" };
        const percent = (current - previous) / Math.abs(previous) * 100;
        const cls = percent === 0 ? "neutral" : inverse ? (percent < 0 ? "positive" : "negative") : (percent >= 0 ? "positive" : "negative");
        return { text: `${Math.abs(percent).toFixed(1)}%`, cls, arrow: percent >= 0 ? "\u25B2" : "\u25BC" };
    }

    grouped(rows, groupBy, targetField = "") {
        const result = {};
        for (const order of rows) {
            const key = groupBy(order) || "-";
            const entry = result[key] || { name: key, value: 0, count: 0, sessions: new Set(), items: 0, target: 0 };
            entry.value += Math.max(0, Number(order.amount || 0));
            entry.count += 1;
            entry.sessions.add(order.session_id);
            entry.items += (order.lines || []).reduce((sum, line) => sum + Math.max(0, Number(line.qty || 0)), 0);
            if (targetField && Number(order[targetField] || 0) > 0) entry.target = Number(order[targetField]);
            result[key] = entry;
        }
        return Object.values(result);
    }

    get outletRows() {
        const previous = Object.fromEntries(this.grouped(this.state.previousFiltered, (order) => order.register).map((row) => [row.name, row.value]));
        const targets = Object.fromEntries((this.state.targets.outlets || []).map((row) => [row.name, row]));
        const total = this.current.net || 1;
        return this.grouped(this.state.filtered, (order) => order.register, "outlet_target").sort((a, b) => b.value - a.value).map((row, index) => ({
            ...row, target: targets[row.name]?.target || 0, achievement: targets[row.name]?.achievement || 0, previous: previous[row.name] || 0, share: row.value / total * 100, color: PAYMENT_COLORS[index % PAYMENT_COLORS.length], growth: this.growth(row.value, previous[row.name] || 0),
        }));
    }

    get employeeRows() {
        const previous = Object.fromEntries(this.grouped(this.state.previousFiltered, (order) => order.employee).map((row) => [row.name, row.value]));
        const targets = Object.fromEntries((this.state.targets.officers || []).map((row) => [row.name, row]));
        return this.grouped(this.state.filtered, (order) => order.employee, "officer_target").sort((a, b) => b.value - a.value).map((row, index) => {
            const target = targets[row.name]?.target || 0;
            return { ...row, rank: index + 1, register: this.state.filtered.find((order) => order.employee === row.name)?.register || "", previous: previous[row.name] || 0, target, achievement: targets[row.name]?.achievement || 0, growth: this.growth(row.value, previous[row.name] || 0), initials: row.name.slice(0, 2).toUpperCase() };
        });
    }

    get productRows() {
        const products = {};
        const previous = {};
        for (const order of this.state.filtered) for (const line of (order.lines || [])) {
            const product = products[line.product] || { name: line.product, category: line.category, image: line.image, qty: 0, value: 0 };
            product.qty += Math.max(0, Number(line.qty || 0));
            product.value += Math.max(0, Number(line.amount || 0));
            products[line.product] = product;
        }
        for (const order of this.state.previousFiltered) for (const line of (order.lines || [])) previous[line.product] = (previous[line.product] || 0) + Math.max(0, Number(line.amount || 0));
        return Object.values(products).sort((a, b) => b.qty - a.qty).slice(0, 6).map((product) => ({ ...product, previous: previous[product.name] || 0, growth: this.growth(product.value, previous[product.name] || 0) }));
    }

    get categoryRows() {
        const categories = {};
        for (const order of this.state.filtered) for (const line of (order.lines || [])) categories[line.category] = (categories[line.category] || 0) + Math.max(0, Number(line.amount || 0));
        return Object.entries(categories).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([name, value], index) => ({ name, value, color: CATEGORY_COLORS[index % CATEGORY_COLORS.length], share: this.current.net ? value / this.current.net * 100 : 0 }));
    }

    get paymentRows() {
        const payments = {};
        for (const order of this.state.filtered) {
            if (order.payment_lines?.length) for (const payment of order.payment_lines) payments[payment.name] = (payments[payment.name] || 0) + Math.max(0, Number(payment.amount || 0));
            else if (order.payment) payments[order.payment] = (payments[order.payment] || 0) + Math.max(0, Number(order.amount || 0));
        }
        return Object.entries(payments).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([name, value], index) => ({ name, value, color: PAYMENT_COLORS[index % PAYMENT_COLORS.length], share: this.current.net ? value / this.current.net * 100 : 0 }));
    }

    get paymentGradient() {
        let cursor = 0;
        return this.paymentRows.map((row) => { const start = cursor; cursor += row.share; return `${row.color} ${start}% ${cursor}%`; }).join(",") || "#eeeae6 0 100%";
    }

    get outletGradient() {
        let cursor = 0;
        return this.outletRows.map((row) => { const start = cursor; cursor += row.share; return `${row.color} ${start}% ${cursor}%`; }).join(",") || "#eeeae6 0 100%";
    }

    get hourRows() {
        const rows = Array.from({ length: 15 }, (_, index) => ({ hour: index + 8, count: 0 }));
        for (const order of this.state.filtered) { const date = orderDate(order); if (date && date.getHours() >= 8 && date.getHours() <= 22) rows[date.getHours() - 8].count += 1; }
        const max = Math.max(1, ...rows.map((row) => row.count));
        return rows.map((row) => ({ ...row, height: row.count / max * 100, peak: row.count >= max * 0.72 }));
    }

    get heatRows() {
        const names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        const hours = [8, 10, 12, 14, 16, 18, 20, 22];
        const cells = names.map((name, day) => ({ name, cells: hours.map((hour) => ({ hour, value: this.state.filtered.filter((order) => { const date = orderDate(order); return date && date.getDay() === day && date.getHours() >= hour && date.getHours() < hour + 2; }).length })) }));
        const max = Math.max(1, ...cells.flatMap((row) => row.cells.map((cell) => cell.value)));
        return cells.map((row) => ({ ...row, cells: row.cells.map((cell) => ({ ...cell, level: Math.min(4, Math.round(cell.value / max * 4)) })) }));
    }

    heatColor(level) { return HEAT_COLORS[Math.max(0, Math.min(HEAT_COLORS.length - 1, level))]; }

    get targetRows() {
        return this.outletRows.map((row) => ({ ...row, attainment: row.achievement }));
    }

    get trend() {
        const bucket = (rows) => {
            const result = {};
            for (const order of rows) { const key = (order.date || "").slice(8, 10) || ""; if (key) result[key] = (result[key] || 0) + Math.max(0, Number(order.amount || 0)); }
            return result;
        };
        const current = bucket(this.state.filtered);
        const previous = bucket(this.state.previousFiltered);
        const labels = [...new Set([...Object.keys(current), ...Object.keys(previous)])].sort((a, b) => Number(a) - Number(b));
        const max = Math.max(1, ...labels.map((label) => Math.max(current[label] || 0, previous[label] || 0)));
        const x = (index) => labels.length < 2 ? 50 : 50 + index / (labels.length - 1) * 710;
        const y = (value) => 226 - value / max * 190;
        const path = (values) => labels.map((label, index) => `${index ? "L" : "M"}${x(index).toFixed(1)} ${y(values[label] || 0).toFixed(1)}`).join(" ");
        const currentValues = labels.map((label) => current[label] || 0);
        const previousValues = labels.map((label) => previous[label] || 0);
        return { labels, current: path(current), previous: path(previous), currentValues, previousValues, total: this.current.net, peak: labels[currentValues.indexOf(Math.max(...currentValues))] || "-" };
    }

    get cards() {
        return [
            { key: "net", label: "Net Sales", value: this.current.net, previous: this.previousStats.net, inverse: false, trend: this.sparkline(this.state.filtered, true) },
            { key: "orders", label: "Orders", value: this.current.orders, previous: this.previousStats.orders, inverse: false, trend: this.sparkline(this.state.filtered, false) },
            { key: "basket", label: "Avg. Basket", value: this.current.aov, previous: this.previousStats.aov, inverse: false, trend: this.sparkline(this.state.filtered, false) },
            { key: "items", label: "Items Sold", value: this.current.items, previous: this.previousStats.items, inverse: false, trend: this.sparkline(this.state.filtered, false) },
            { key: "discount", label: "Discounts", value: this.current.discounts, previous: this.previousStats.discounts, inverse: true, trend: this.sparkline(this.state.filtered, false) },
            { key: "refund", label: "Refunds / Voids", value: this.current.refunds, previous: this.previousStats.refunds, inverse: true, trend: this.sparkline(this.state.filtered, true) },
        ];
    }

    cardValue(card) { return ["orders", "items"].includes(card.key) ? card.value.toLocaleString("en-US") : this.thousand(card.value); }

    sparkline(rows, negative) {
        const values = Array.from({ length: 8 }, () => 0);
        for (const order of rows) { const date = orderDate(order); if (date) values[Math.min(7, date.getDate() % 8)] += Math.abs(Number(order.amount || 0)); }
        const max = Math.max(1, ...values);
        return values.map((value, index) => `${index ? "L" : "M"}${(index * 20).toFixed(1)} ${(38 - value / max * 28).toFixed(1)}`).join(" ");
    }

    onFilter(name, event) { this.state[name] = event.target.value; this.applyFilters(); }
    onRegister(event) { this.onFilter("register", event); }
    onEmployee(event) { this.onFilter("employee", event); }
    onCategory(event) { this.onFilter("category", event); }
    onPayment(event) { this.onFilter("payment", event); }
    setGran(event) { this.state.gran = event.currentTarget.dataset.gran; }

    async onPeriod(event) {
        const period = event.target.value;
        const now = new Date();
        let from = new Date(now.getFullYear(), now.getMonth(), 1);
        let to = now;
        if (period === "today") from = to = now;
        if (period === "yesterday") { from = new Date(now); from.setDate(now.getDate() - 1); to = from; }
        if (period === "week") { from = new Date(now); from.setDate(now.getDate() - 6); }
        if (period === "lastmonth") { from = new Date(now.getFullYear(), now.getMonth() - 1, 1); to = new Date(now.getFullYear(), now.getMonth(), 0); }
        if (period === "quarter") from = new Date(now.getFullYear(), now.getMonth() - 2, 1);
        if (period === "year") from = new Date(now.getFullYear(), 0, 1);
        this.state.period = period;
        this.state.dateFrom = iso(from);
        this.state.dateTo = iso(to);
        if (period !== "custom") await this.load();
    }

    async setQuick(event) { await this.onPeriod({ target: { value: event.currentTarget.dataset.period } }); }
    async apply() { await this.load(); }
    async refresh() { await this.load(); }

    async reset() {
        const now = new Date();
        this.state.period = "month";
        this.state.dateFrom = iso(new Date(now.getFullYear(), now.getMonth(), 1));
        this.state.dateTo = iso(now);
        this.state.register = ""; this.state.employee = ""; this.state.category = ""; this.state.payment = "";
        await this.load();
    }

    onTrendMove(event) {
        const trend = this.trend;
        if (!trend.labels.length) return;
        const box = event.currentTarget.getBoundingClientRect();
        const ratio = box.width ? Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)) : 0;
        const index = Math.round(ratio * (trend.labels.length - 1));
        this.state.tip = { label: trend.labels[index], current: this.thousand(trend.currentValues[index]), previous: this.thousand(trend.previousValues[index]), left: event.clientX + 12, top: event.clientY + 12 };
    }

    onTrendLeave() { this.state.tip = null; }

    exportCsv() {
        const rows = [["Order", "Date", "Customer", "Cashier", "Outlet", "Amount", "Payment", "Status"], ...this.state.filtered.map((order) => [order.name, order.date, order.customer, order.employee, order.register, order.amount, order.payment, order.state])]
            .map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(","));
        const url = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8" }));
        const anchor = document.createElement("a");
        anchor.href = url; anchor.download = "pos-sales-dashboard.csv"; document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url);
    }
}

registry.category("actions").add("zencore_pos_dashboard.sales_dashboard", PosSalesDashboard);
