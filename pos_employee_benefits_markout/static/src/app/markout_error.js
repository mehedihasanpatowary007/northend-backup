import { _t } from '@web/core/l10n/translation';
import { ConnectionAbortedError, ConnectionLostError } from '@web/core/network/rpc';

const BUSINESS_EXCEPTIONS = new Set([
    'odoo.exceptions.UserError',
    'odoo.exceptions.ValidationError',
    'odoo.exceptions.AccessError',
]);

export function markoutErrorMessage(error, fallback) {
    // RPCError.message is only the generic envelope ("Odoo Server Error").
    // The useful server message is in data.message. Never show the traceback
    // stored in data.debug; shorten any unexpected server error to one line.
    const exceptionName = error?.exceptionName || error?.data?.name;
    const rawMessage = error?.data?.message || error?.data?.arguments?.[0];
    const message = typeof rawMessage === 'string'
        ? rawMessage.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || ''
        : '';
    if (BUSINESS_EXCEPTIONS.has(exceptionName)) {
        if (message) return message.slice(0, 240);
    } else if (error?.type === 'server' && message && message !== 'Odoo Server Error') {
        return _t('Server error: %s', message.slice(0, 180));
    }
    if (error instanceof ConnectionLostError) {
        return _t('The server connection was lost. Reconnect and retry with the same cart.');
    }
    if (error instanceof ConnectionAbortedError) {
        return _t('The request was interrupted. Retry with the same cart.');
    }
    // Locally raised Error messages describe actionable client-side checks.
    if (error?.constructor === Error && !error.data && !exceptionName
            && typeof error.message === 'string' && error.message.trim()) {
        return error.message;
    }
    return fallback;
}
