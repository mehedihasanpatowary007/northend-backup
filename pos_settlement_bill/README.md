# POS Settlement Bill

Odoo 19 addon for printing a clean unpaid customer bill directly from the product screen. **Settlement Bill** and **Payment** appear side by side in the cart, including the cart view on compact screens. Both actions share the same row, while native customer and order tools retain their full width.

Settlement Bill is hidden while the cart is empty and appears when a product is
added. Customer and Order Note remain compact icons in the register; the Actions
popup shows full-size labeled tiles together in its native grid. Each note entry
appears only once in the popup.

## Setup

1. Install **POS Settlement Bill** from Apps. It depends on the native POS Employees addon (`pos_hr`).
2. Enable employee login for the register and assign its allowed employees in the native POS settings.
3. An HR administrator opens **Employees → employee → Settings**, enables **Print Settlement Bills**, and sets the employee's existing **PIN Code**. Permission defaults to off. No separate PIN, badge, or employee mapping is introduced.
4. Reload the POS and log in as the employee.

## Printing

Add products to an unpaid cart, select **Settlement Bill**, and enter the current cashier's employee PIN. The server verifies the open session, company, allowed employee, explicit print permission, and PIN for every request. Cancelling the prompt does not print. Five wrong PIN attempts temporarily block further attempts for that employee for one minute. A server connection is required for approval.

The bill is a snapshot of the cart and identifies itself as **Payment pending**. It includes the business details, order and table information when present, customer, items, discounts, tax breakdown, and total. It uses native POS pricing and the installed custom discount getters. Cash-only rounding is finalized when the payment method is selected; the bill explains this when applicable.

Printing uses the native POS receipt printer, with browser printing when no device is configured. It does not validate, submit, pay, or invoice the order, and it does not increment the paid receipt print counter. Reprints require a fresh PIN approval. Empty carts, refund carts, and Marked Out carts do not produce settlement bills. An order with payment amounts or terminal payment status already entered must complete or cancel that payment first; a settlement bill is for the pre-payment cart.

PIN values are submitted only for the current authorization request. They are not added to order data, returned by the server, cached as approvals, or saved in browser storage. The bill records the approving employee's name. If the cart or cashier changes during authorization, the cashier must review it and print again.

## Order notes - 19.0.1.1.0

The main **Note** action and the Actions-menu customer note become **Order Note**.
They always edit the whole ticket, including when a product line is selected.
The popup opens the ticket's current note. Save replaces it; saving empty text
clears it; Cancel preserves it. The line selection and product quantities are
not changed. A changed or finalized ticket cannot receive another ticket's note.

The existing native `pos.order.general_customer_note` field retains the note
through Odoo's normal local storage and order synchronization. The cart, standard
paid receipt and reprints show it once in a labeled **Order Note** section with
line breaks preserved. Settlement Bill uses the same field and label. Existing
line notes remain on their original records; the new actions do not create them.
Upgrade this existing addon and reload the POS to apply the change.

The POS **Orders** list also shows the same note in a dedicated **Order Note**
column next to the order reference. Long notes show two lines with the complete
text available on hover; opening the order shows the full note in its summary.
Compact screens show the note below the order reference. This uses the existing
native order field for both current and synchronized historical orders.

No live Odoo or printer tests were run, following the requested development preference. Source, manifest, and template checks are performed separately.

## Keyboard shortcuts

Hold **Alt** in the register to show the available shortcut keys on the buttons:

| Shortcut | Action |
| --- | --- |
| Alt+C | Customer |
| Alt+N | Order Note |
| Alt+M | Marked Out (when installed and permitted) |
| Alt+P | Payment |
| Alt+B | Settlement Bill |

These use Odoo's native hotkey overlays and the existing button actions. Hidden
or disabled actions remain unavailable, and shortcuts respect the active dialog.
Settlement Bill still requires employee permission and PIN approval on every
print. Payment's shortcut is not assigned to Refund or Confirm Marked Out.
Upgrade **POS Settlement Bill** and **POS Employee Benefits & Marked Out**, then
reload the POS to load the updated templates.
