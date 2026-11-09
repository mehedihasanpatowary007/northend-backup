import { Component, onWillStart, onWillDestroy, useEffect, useRef, useState } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { patch } from '@web/core/utils/patch';
import { useService } from '@web/core/utils/hooks';
import { _t } from '@web/core/l10n/translation';
import { AlertDialog, ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import { ControlButtons } from '@point_of_sale/app/screens/product_screen/control_buttons/control_buttons';
import { ProductScreen } from '@point_of_sale/app/screens/product_screen/product_screen';
import { PosStore } from '@point_of_sale/app/services/pos_store';
import { usePos } from '@point_of_sale/app/hooks/pos_hook';
import { markoutErrorMessage } from './markout_error';


function storageKey(pos) {
    return `pos_markout_drafts_${pos.config.id}_${pos.user?.id || 0}`;
}

function markoutDrafts(pos) {
    if (!pos.markoutDrafts) {
        try {
            pos.markoutDrafts = JSON.parse(window.localStorage.getItem(storageKey(pos)) || '{}');
        } catch {
            pos.markoutDrafts = {};
        }
    }
    return pos.markoutDrafts;
}

function saveMarkoutDrafts(pos) {
    window.localStorage.setItem(storageKey(pos), JSON.stringify(markoutDrafts(pos)));
}

function contextFor(pos, order = pos.getOrder()) {
    return order ? markoutDrafts(pos)[order.uuid] || null : null;
}

function restoreOrder(pos, previousUuid) {
    const previous = previousUuid && pos.models['pos.order'].getBy('uuid', previousUuid);
    const order = previous || pos.addNewOrder();
    pos.setOrder(order);
    pos.navigate('ProductScreen', { orderUuid: order.uuid });
}

async function cancelMarkoutDraft(pos, dialog) {
    const order = pos.getOrder();
    const context = contextFor(pos, order);
    if (!context) return;
    dialog.add(ConfirmationDialog, {
        title: _t('Cancel Marked Out?'),
        body: _t('The cart will be discarded. No marked-out record or stock movement has been created.'),
        confirm: async () => {
            delete markoutDrafts(pos)[order.uuid];
            saveMarkoutDrafts(pos);
            await pos.removeOrder(order, false);
            restoreOrder(pos, context.previousOrderUuid);
        },
    });
}

async function finishMarkout(pos, order, context, result) {
    delete markoutDrafts(pos)[order.uuid];
    saveMarkoutDrafts(pos);
    await pos.removeOrder(order, false);
    restoreOrder(pos, context.previousOrderUuid);
    pos.notification.add(_t('Marked Out %s confirmed.', result.reference), { type: 'success' });
}


export class MarkedOutScreen extends Component {
    static template = 'pos_employee_benefits_markout.MarkedOutScreen';
    static props = { previousOrderUuid: String };
    static storeOnOrder = false;

    setup() {
        this.orm = useService('orm');
        this.dialog = useService('dialog');
        this.pos = usePos();
        this.state = useState({ categories: [], parent: null, child: null,
            query: '', employees: [], selectedEmployee: null, searching: false, busy: false, error: '' });
        this.employeeSearch = useRef('employeeSearch');
        useEffect(() => {
            this.employeeSearch.el?.focus();
        }, () => [this.state.child?.id]);
        this.alive = true;
        this.searchGeneration = 0;
        onWillDestroy(() => {
            this.alive = false;
            this.searchGeneration++;
            clearTimeout(this.searchTimer);
        });
        onWillStart(async () => {
            try {
                const result = await this.orm.call('pos.markout', 'get_pos_setup', [this.pos.session.id, this.pos.config.id]);
                if (!this.alive) return;
                this.state.categories = result.categories || [];
                this.state.parent = this.state.categories[0] || null;
                if (!this.state.categories.length) this.state.error = _t('No permitted Marked Out subcategories are assigned to your user.');
                else await this.searchEmployees();
            } catch (error) {
                if (!this.alive) return;
                this.state.error = markoutErrorMessage(error, _t('Marked Out is not available for this user or POS session.'));
            }
        });
    }

    async selectParent(parent) {
        if (this.state.busy || this.state.parent?.id === parent.id) return;
        this.resetEmployeeSearch();
        this.state.parent = parent;
        this.state.child = null;
        this.state.error = '';
        await this.searchEmployees();
    }

    categoryIcon(parent) {
        const icons = { staff: 'fa-users', cafe: 'fa-coffee', corporate: 'fa-building-o' };
        return `fa ${parent?.icon || icons[parent?.code] || 'fa-gift'}`;
    }

    employeeInitials(employee) {
        return (employee.name || '').trim().split(/\s+/).slice(0, 2)
            .map((part) => part[0] || '').join('').toUpperCase() || '?';
    }

    async selectChild(child) {
        if (this.state.busy || this.state.child?.id === child.id) return;
        this.resetEmployeeSearch();
        this.state.child = child;
        this.state.error = '';
        await this.searchEmployees();
    }

    resetEmployeeSearch() {
        clearTimeout(this.searchTimer);
        this.searchGeneration++;
        this.state.query = '';
        this.state.selectedEmployee = null;
        this.state.searching = false;
    }

    queryChanged(event) {
        if (this.state.busy) return;
        this.state.query = event.target.value;
        this.state.selectedEmployee = null;
        this.state.employees = [];
        this.state.error = '';
        this.searchGeneration++;
        this.state.searching = false;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => this.searchEmployees(), 300);
    }

    onSearchKeydown(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            this.searchEmployees();
        }
    }

    async searchEmployees() {
        if (!this.state.categories.length || this.state.busy || !this.alive) return;
        clearTimeout(this.searchTimer);
        const generation = ++this.searchGeneration;
        const categoryId = this.state.child?.id || null;
        this.state.searching = true;
        this.state.selectedEmployee = null;
        this.state.error = '';
        try {
            const employees = await this.orm.call('pos.markout', 'search_pos_employees', [
                this.pos.session.id, this.pos.config.id, categoryId, this.state.query.trim(),
            ]);
            if (!this.alive || generation !== this.searchGeneration) return;
            this.state.employees = employees;
        } catch (error) {
            if (!this.alive || generation !== this.searchGeneration) return;
            this.state.employees = [];
            this.state.error = markoutErrorMessage(error, _t('Employee search failed.'));
        } finally {
            if (this.alive && generation === this.searchGeneration) this.state.searching = false;
        }
    }

    async selectEmployee(employee) {
        if (this.state.busy || this.state.searching || !this.alive
                || !this.state.employees.some((item) => item.id === employee.id)) return;
        if (!this.state.child) {
            this.dialog.add(AlertDialog, {
                title: _t('Select a Subcategory'),
                body: _t('Please select a subcategory first.'),
            });
            return;
        }
        if (employee.benefit_restricted && !employee.benefit_product_ids?.length) {
            this.dialog.add(AlertDialog, {
                title: _t('No Benefit Allowance'),
                body: _t('No active product allowance is configured for this employee and subcategory. Set it in Employees → POS Benefits.'),
            });
            return;
        }
        this.state.selectedEmployee = employee;
        this.state.error = employee.partner_id ? '' : _t('This employee has no active work contact for this company. Set the work contact in Employees before continuing.');
        if (employee.partner_id) await this.continueToCart();
    }

    returnToRegister() {
        if (this.state.busy) return;
        restoreOrder(this.pos, this.props.previousOrderUuid);
    }

    async continueToCart() {
        const employee = this.state.selectedEmployee;
        const parent = this.state.parent;
        const child = this.state.child;
        if (!employee?.partner_id || !child || !parent || this.state.busy || this.state.searching) return;
        this.state.busy = true;
        this.state.error = '';
        let cartOpened = false;
        try {
            const partnerModel = this.pos.models['res.partner'];
            let partner = partnerModel.get(employee.partner_id);
            if (!partner) {
                const partners = await this.pos.data.searchRead('res.partner', [['id', '=', employee.partner_id]]);
                partner = partners[0];
            }
            if (!this.alive) return;
            if (!partner || partner.id !== employee.partner_id) {
                throw new Error(_t('The employee work contact could not be loaded. Check the contact and connection.'));
            }
            const order = this.pos.addNewOrder();
            order.partner_id = partner;
            order.to_invoice = false;
            this.pos.numpadMode = 'quantity';
            markoutDrafts(this.pos)[order.uuid] = {
                sessionId: this.pos.session.id, configId: this.pos.config.id,
                parentId: parent.id, parentName: parent.name,
                categoryId: child.id, categoryName: child.name,
                allowedProductIds: employee.benefit_restricted
                    ? employee.benefit_product_ids : child.product_ids || [],
                employeeId: employee.id, employeeName: employee.name,
                employeeMapping: 'native_hr_v1',
                partnerId: employee.partner_id, previousOrderUuid: this.props.previousOrderUuid,
                requestUuid: order.uuid,
            };
            saveMarkoutDrafts(this.pos);
            this.pos.navigate('ProductScreen', { orderUuid: order.uuid });
            cartOpened = true;
        } catch (error) {
            if (this.alive) this.state.error = markoutErrorMessage(error, _t('Could not load the employee work contact. Try again.'));
        } finally {
            // Keep the selection locked until navigation unmounts this screen.
            if (this.alive && !cartOpened) this.state.busy = false;
        }
    }
}

registry.category('pos_pages').add('MarkedOutScreen', {
    name: 'MarkedOutScreen', component: MarkedOutScreen,
    route: `/pos/ui/${odoo.pos_config_id}/marked-out/{string:previousOrderUuid}`,
    params: {},
});

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.markoutAccess = useState({ ready: false, allowed: false });
        onWillStart(async () => {
            try {
                const session = this.pos.session;
                if (!session || !this.pos.config) return;
                await this.env.services.orm.call('pos.markout', 'get_pos_setup', [session.id, this.pos.config.id]);
                this.markoutAccess.allowed = true;
            } catch {
                this.markoutAccess.allowed = false;
            } finally {
                this.markoutAccess.ready = true;
            }
        });
    },
    get isMarkoutOrder() {
        return Boolean(contextFor(this.pos));
    },
    async startMarkedOut() {
        const previousOrderUuid = this.pos.getOrder()?.uuid || this.pos.addNewOrder().uuid;
        this.props.close?.();
        this.pos.navigate('MarkedOutScreen', { previousOrderUuid });
    },
    cancelMarkedOut() {
        return cancelMarkoutDraft(this.pos, this.dialog);
    },
});


patch(ProductScreen.prototype, {
    get markoutContext() {
        return contextFor(this.pos, this.currentOrder);
    },
    get isMarkoutOrder() {
        return Boolean(this.markoutContext);
    },
    get total() {
        return this.isMarkoutOrder ? 0 : super.total;
    },
    cancelMarkedOut() {
        return cancelMarkoutDraft(this.pos, this.dialog);
    },
    getNumpadButtons() {
        const buttons = super.getNumpadButtons(...arguments);
        return this.isMarkoutOrder
            ? buttons.map((button) => ({ ...button,
                disabled: button.disabled || ['discount', 'price'].includes(button.value),
            }))
            : buttons;
    },
    onNumpadClick(value) {
        if (this.isMarkoutOrder && ['discount', 'price'].includes(value)) return;
        return super.onNumpadClick(...arguments);
    },
    async addProductToOrder(product) {
        const allowedProductIds = this.markoutContext?.allowedProductIds || [];
        const allowedByTemplate = product.product_variant_ids?.some((variant) => allowedProductIds.includes(variant.id));
        if (allowedProductIds.length && !allowedProductIds.includes(product.id) && !allowedByTemplate) {
            this.dialog.add(AlertDialog, {
                title: _t('Product Not Allowed'),
                body: _t('This product is not permitted for the selected Marked Out category.'),
            });
            return;
        }
        return super.addProductToOrder(...arguments);
    },
});


patch(PosStore.prototype, {
    isMarkoutOrder(order = this.getOrder()) {
        return Boolean(contextFor(this, order));
    },
    shouldCreatePendingOrder(order) {
        return this.isMarkoutOrder(order) ? false : super.shouldCreatePendingOrder(...arguments);
    },
    setPartnerToCurrentOrder(partner) {
        const context = contextFor(this);
        if (context && partner?.id !== context.partnerId) return;
        return super.setPartnerToCurrentOrder(...arguments);
    },
    async addLineToOrder(vals, order, opts = {}, configure = true) {
        const line = await super.addLineToOrder(...arguments);
        if (this.isMarkoutOrder(order)) {
            order.lines.forEach((orderLine) => orderLine.setUnitPrice(0));
        }
        return line;
    },
    async pay() {
        const order = this.getOrder();
        const context = contextFor(this, order);
        if (!context) return super.pay(...arguments);
        if (this.markoutBusy) return;
        if (this.data.network.offline || !navigator.onLine) {
            this.dialog.add(AlertDialog, {
                title: _t('Connection Required'),
                body: _t('Marked Out requires a live server connection. This cart is still saved on this device.'),
            });
            return;
        }
        if (context.employeeMapping !== 'native_hr_v1') {
            this.markoutBusy = true;
            try {
                const result = await this.data.call('pos.markout', 'get_markout_status', [
                    context.sessionId, context.configId, context.requestUuid,
                ]);
                if (result.state === 'confirmed') {
                    await finishMarkout(this, order, context, result);
                    return;
                }
                this.dialog.add(AlertDialog, {
                    title: _t('Select Employee Again'),
                    body: _t('This saved cart uses the previous employee mapping. Cancel Marked Out and select the employee again to use their current Work Contact.'),
                });
            } catch {
                this.dialog.add(AlertDialog, {
                    title: _t('Cannot Verify Saved Marked Out'),
                    body: _t('Reconnect and retry confirmation to check whether this saved request was already completed. Keep this cart until its status is verified.'),
                });
            } finally {
                this.markoutBusy = false;
            }
            return;
        }
        if (!order.lines.length) {
            this.dialog.add(AlertDialog, { title: _t('No Items'), body: _t('Add at least one product before confirming Marked Out.') });
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t('Confirm Marked Out?'),
            body: _t('Payable: 0. No payment record will be created. Confirm the employee, reason, quantities, and stock handling.'),
            confirmLabel: _t('Confirm Marked Out'),
            confirm: async () => {
                this.markoutBusy = true;
                try {
                    const lines = order.lines.map((line) => ({
                        product_id: line.product_id.id,
                        qty: line.qty,
                        is_combo: Boolean(line.combo_parent_id || line.combo_line_ids?.length || line.product_id.type === 'combo'),
                        note: (typeof line.getNote === 'function' ? line.getNote() : line.note) || '',
                    }));
                    const result = await this.data.call('pos.markout', 'submit_markout', [
                        context.sessionId, context.configId, context.categoryId, context.employeeId,
                        context.requestUuid, lines, order.general_customer_note || '',
                    ]);
                    await finishMarkout(this, order, context, result);
                } catch (error) {
                    try {
                        const recovered = await this.data.call('pos.markout', 'get_markout_status', [
                            context.sessionId, context.configId, context.requestUuid,
                        ]);
                        if (recovered.state === 'confirmed') {
                            await finishMarkout(this, order, context, recovered);
                            return;
                        }
                    } catch {
                        // Keep the original cart and request UUID so the cashier can safely retry.
                    }
                    this.dialog.add(AlertDialog, {
                        title: _t('Cannot Confirm Marked Out'),
                        body: markoutErrorMessage(error, _t('The server did not confirm this request. Retry with the same cart; do not create a second request.')),
                    });
                } finally {
                    this.markoutBusy = false;
                }
            },
        });
    },
});
