import { onWillDestroy, useState } from '@odoo/owl';
import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { AlertDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import { ProductScreen } from '@point_of_sale/app/screens/product_screen/product_screen';
import { NumberPopup } from '@point_of_sale/app/components/popups/number_popup/number_popup';
import { BACKSPACE, ZERO, getButtons } from '@point_of_sale/app/components/numpad/numpad';
import { SettlementReceipt, buildSettlementReceipt } from './settlement_receipt';

const PIN_PATTERN = /^[0-9]{1,64}$/;

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.settlementBillState = useState({ busy: false });
        // Raw services plus explicit lifecycle checks allow cleanup even if the
        // screen is destroyed while an authorization request is in flight.
        this.settlementBillOrm = this.env.services.orm;
        this.settlementBillPrinter = this.env.services.printer;
        this.settlementBillAlive = true;
        onWillDestroy(() => {
            this.settlementBillAlive = false;
            this.closeSettlementPin?.();
            if (this.pos._settlementBillInProgress === this.settlementBillAttempt) {
                this.pos._settlementBillInProgress = null;
            }
        });
    },

    get settlementBillAvailable() {
        const order = this.currentOrder;
        return Boolean(order && order.state === 'draft' && !order.isEmpty()
            && !order.isRefund && !this.isMarkoutOrder);
    },

    get settlementBillPaymentStarted() {
        return Boolean(this.currentOrder?.payment_ids.some(
            (payment) => payment.amount || payment.payment_status,
        ));
    },

    async printSettlementBill() {
        if (!this.settlementBillAvailable || this.settlementBillState.busy
            || this.pos._settlementBillInProgress || this.settlementBillPrinter.state.isPrinting) {
            return;
        }
        if (!this.pos.config.module_pos_hr || !this.pos.cashier?.id) {
            this.dialog.add(AlertDialog, {
                title: _t('Employee Login Required'),
                body: _t('Log in to this POS with an employee before printing a settlement bill.'),
            });
            return;
        }
        if (this.settlementBillPaymentStarted) {
            this.dialog.add(AlertDialog, {
                title: _t('Payment Already Started'),
                body: _t('Complete or cancel the current payment before printing an unpaid settlement bill.'),
            });
            return;
        }
        if (this.pos.data.network.offline) {
            this.dialog.add(AlertDialog, {
                title: _t('Connection Required'),
                body: _t('Connect to the server so your settlement bill permission and PIN can be verified.'),
            });
            return;
        }

        this.settlementBillState.busy = true;
        const attempt = Symbol('settlement-bill');
        this.settlementBillAttempt = attempt;
        this.pos._settlementBillInProgress = attempt;
        let pin;
        try {
            // Apply any pending quantity input before taking the bill snapshot.
            this.numberBuffer.capture();
            const order = this.currentOrder;
            const cashier = this.pos.cashier;
            const snapshotAuthorization = {
                employee_name: cashier.name,
                printed_at: luxon.DateTime.utc().toFormat('yyyy-MM-dd HH:mm:ss'),
            };
            const snapshot = JSON.stringify(buildSettlementReceipt(this.pos, order, snapshotAuthorization));
            pin = await new Promise((resolve) => {
                this.closeSettlementPin = this.dialog.add(NumberPopup, {
                    title: _t('Settlement Bill PIN'),
                    startingValue: '',
                    placeholder: _t('Employee PIN'),
                    confirmButtonLabel: _t('Verify & Print'),
                    buttons: getButtons([{ value: '', disabled: true }, ZERO, BACKSPACE]),
                    formatDisplayedValue: (value) => '•'.repeat(String(value).length),
                    isValid: (value) => typeof value === 'string' && PIN_PATTERN.test(value),
                    getPayload: resolve,
                }, {
                    onClose: () => {
                        this.closeSettlementPin = null;
                        resolve();
                    },
                });
            });
            if (!this.settlementBillAlive || typeof pin !== 'string' || !PIN_PATTERN.test(pin)) return;

            let authorization;
            try {
                authorization = await this.settlementBillOrm.call(
                    'pos.session', 'authorize_settlement_bill',
                    [[this.pos.session.id], cashier.id, pin],
                );
            } finally {
                // Credentials belong to this single request, never the cart or storage.
                pin = undefined;
            }
            if (!this.settlementBillAlive) return;
            if (!authorization?.authorized) {
                this.dialog.add(AlertDialog, {
                    title: _t('Cannot Print Settlement Bill'),
                    body: authorization?.error || _t('Your employee PIN could not be verified.'),
                });
                return;
            }
            if (!this.settlementBillAvailable || this.settlementBillPaymentStarted || this.currentOrder !== order
                || this.pos.cashier?.id !== cashier.id
                || JSON.stringify(buildSettlementReceipt(this.pos, order, snapshotAuthorization)) !== snapshot) {
                this.dialog.add(AlertDialog, {
                    title: _t('Order Changed'),
                    body: _t('The order or cashier changed while approving the bill. Review the cart and print again.'),
                });
                return;
            }

            const data = buildSettlementReceipt(this.pos, order, authorization);
            // Use the native printer without validating the order or changing paid-receipt counters.
            const result = await this.settlementBillPrinter.print(
                SettlementReceipt, { data }, { webPrintFallback: true },
            );
            if (!result) {
                throw new Error(_t('The bill could not be sent to the printer.'));
            }
        } catch (error) {
            if (this.settlementBillAlive) this.dialog.add(AlertDialog, {
                title: _t('Cannot Print Settlement Bill'),
                body: error?.data?.message || error?.body || error?.message
                    || _t('Check the server connection and receipt printer, then try again.'),
            });
        } finally {
            pin = undefined;
            if (this.pos._settlementBillInProgress === attempt) {
                this.pos._settlementBillInProgress = null;
            }
            if (this.settlementBillAlive) {
                this.numberBuffer.reset();
                this.settlementBillState.busy = false;
            }
        }
    },
});
