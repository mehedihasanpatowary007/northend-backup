import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { AlertDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import { TextInputPopup } from '@point_of_sale/app/components/popups/text_input_popup/text_input_popup';
import { NoteButton } from '@point_of_sale/app/screens/product_screen/control_buttons/orderline_note_button/orderline_note_button';
import { ControlButtons } from '@point_of_sale/app/screens/product_screen/control_buttons/control_buttons';
import { makeAwaitable } from '@point_of_sale/app/utils/make_awaitable_dialog';

class OrderNotePopup extends TextInputPopup {
    static template = 'pos_settlement_bill.OrderNotePopup';
}

class OrderNoteButton extends NoteButton {
    static template = 'pos_settlement_bill.OrderNoteButton';
    static props = {
        ...NoteButton.props,
        iconOnly: { type: Boolean, optional: true },
    };
    static defaultProps = { iconOnly: true };

    get currentNote() {
        return this.pos.getOrder()?.general_customer_note || '';
    }

    get canEditOrderNote() {
        const order = this.pos.getOrder();
        return Boolean(order && order.state === 'draft' && !order.isEmpty());
    }

    async onClick() {
        if (!this.canEditOrderNote || this.pos._orderNoteEditing) return;
        const order = this.pos.getOrder();
        const oldNote = order.general_customer_note || '';
        this.pos._orderNoteEditing = true;
        try {
            const payload = await makeAwaitable(this.dialog, OrderNotePopup, {
                title: _t('Order Note'),
                startingValue: oldNote,
                placeholder: _t('Add a note for this order...'),
                rows: 4,
            });
            if (typeof payload !== 'string') return;
            // Keep the note attached to the exact ticket opened by the cashier.
            if (this.pos.getOrder() !== order || order.state !== 'draft' || order.isEmpty()) {
                this.dialog.add(AlertDialog, {
                    title: _t('Order Changed'),
                    body: _t('The order changed while editing the note. Open Order Note again on the correct ticket.'),
                });
                return;
            }
            const note = payload.trim();
            if (note !== oldNote) {
                order.assertEditable();
                order.setGeneralCustomerNote(note);
            }
            return { confirmed: true, inputNote: note, oldNote };
        } finally {
            this.pos._orderNoteEditing = false;
        }
    }
}

// Both the main Note action and the Actions-menu note edit the same order field.
// Keep the native component names so other addons' visibility rules still apply.
patch(ControlButtons, {
    components: {
        ...ControlButtons.components,
        InternalNoteButton: OrderNoteButton,
        NoteButton: OrderNoteButton,
    },
});
