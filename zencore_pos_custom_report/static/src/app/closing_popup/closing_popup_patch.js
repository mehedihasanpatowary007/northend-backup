import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ConnectionLostError } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { parseFloat } from "@web/views/fields/parsers";

patch(ClosePosPopup.prototype, {
    async closeSession() {
        this.pos._resetConnectedCashier();
        const syncSuccess = await this.pos.pushOrdersWithClosingPopup();
        if (!syncSuccess) {
            return;
        }
        if (this.pos.config.cash_control) {
            const response = await this.pos.data.call(
                "pos.session",
                "post_closing_cash_details",
                [this.pos.session.id],
                {
                    counted_cash: parseFloat(
                        this.state.payments[this.props.default_cash_details.id].counted
                    ),
                }
            );

            if (!response.successful) {
                return this.handleClosingError(response);
            }
        }

        try {
            await this.pos.data.call("pos.session", "update_closing_control_state_session", [
                this.pos.session.id,
                this.state.notes,
            ]);
        } catch (error) {
            if (!error.data && error.data?.message !== "This session is already closed.") {
                throw error;
            }
        }

        try {
            const response = await this.pos.data.call(
                "pos.session",
                "close_session_from_ui",
                [this.pos.session.id, this.bankPaymentMethodDiffPairs],
                {
                    context: {
                        device_identifier: this.pos.device.identifier,
                    },
                }
            );
            if (!response.successful) {
                return this.handleClosingError(response);
            }

            // Check if automated session summary mail failed
            if (response.mail_success === false) {
                await new Promise((resolve) => {
                    this.dialog.add(AlertDialog, {
                        title: _t("Alert"),
                        body: _t("mail sending fail"),
                        confirmLabel: _t("Close"),
                        confirm: () => resolve(),
                        dismiss: () => resolve(),
                    });
                });
            }

            this.pos.session.state = "closed";
            this.pos.router.close();
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                throw error;
            } else {
                await this.handleClosingControlError();
            }
        } finally {
            localStorage.removeItem(`pos.session.${odoo.pos_config_id}`);
        }
    },
});
