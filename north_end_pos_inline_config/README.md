# North End POS inline configuration — Odoo 19

Implements the 19 October 2026 North End Coffee requirements using native POS
products, attributes, prices, tax calculations, order lines, and payments.

## Install

1. Deploy `north_end_pos_inline_config` and `north_end_pos_inline_mrp` to the Odoo addons path.
2. Update the Apps list and install **North End POS Inline Configuration**.
3. When `zencore_pos_auto_mrp` is installed, **North End POS Inline Manufacturing**
   installs automatically as the integration module. It can also be installed explicitly.
4. In the POS configuration, **Coffee order entry** contains the enable switch and
   maximum portions per add-on (default 50; zero removes the limit). The feature
   is enabled by default. Products' existing POS Optional Products field is
   relabeled **Add-ons**; existing mappings are retained.
5. Finish syncing open orders, then reload the POS page to load the new assets
   and fields. An already open browser tab does not acquire the new code automatically.

The existing PoS Product Category **Color** control keeps Odoo's palette and adds
a HEX color picker and text input in the same field. Choose a palette color or
enter a `#RRGGBB` value; the selected color appears on standard and vertical POS
category buttons. Upgrading from a version with the separate Custom HEX Color
field migrates saved HEX values into this native Color field.

No new products, sample prices, taxes, categories, warehouses, or BoMs are created.
Configure sellable add-on products, their POS availability, prices, taxes, and
recipes in the existing product forms. A sellable `Extra Milk` recipe may consume
the existing raw milk product; raw ingredients need not be sold as add-ons.

## Order entry

- The standard left cart, keypad, top bar, product cards, and payment remain.
  Categories form a vertical column. Variant options and add-on steppers appear
  below the grid for the selected item and disappear when there are no options.
- Tapping a product adds one cup immediately. Repeating it increments the
  selected variant. Barcode entry retains Odoo's normal barcode flow.
- Standard untracked, non-weighted, non-combo products use inline configuration,
  including dynamic variants, attribute exclusions, custom values, and multiple
  selection attributes. Dynamic variant creation needs an online connection.
  Scales, combo selection, and lot/serial capture keep their native workflows.
- Changing a variant moves one cup from a multiple-quantity line. Existing
  add-ons stay on the source line. A one-cup line carries its add-ons to the new
  variant. Kitchen-sent items retain Odoo's restriction against reconfiguration.
- On first use, a configured product refreshes its variants, attribute values
  and exclusions through Odoo's native product loader. Requests are shared
  between the register and inline editor and reused for that POS page session.
  Existing offline combinations remain usable if the connection is unavailable.
  Archived combinations are matched to the full variant; an older Size-only
  archived variant does not block active Size + Brand variants. Native attribute
  exclusions still apply, including exclusions on non-variant modifiers. Saved
  single-choice attributes are normalized against the current product values.
  Inactive attribute values retained for old orders are filtered out after
  on-demand refresh, including dynamic choices and non-variant modifiers.
- Compatible lines merge; quantities of matching add-ons are added, never
  multiplied. Different prices, taxes, discounts, custom text, lots, refunds,
  and fixed discounts are not silently combined. Manual variant prices remain
  manual. Original prices use the active pricelist.
- Coffee quantity changes do not modify any add-on quantity. Zero on the coffee
  keypad removes the group; an add-on minus button removes the row at zero.
  Removing a parent also removes its children. Zero-price add-ons remain visible.
- Add-on variants are listed separately by their existing Odoo variant names.
  Quantity limits apply per variant per parent. The server enforces mapping,
  parent membership, quantity, and nonnegative-price rules before finalization.
- Quantity reduction restrictions also apply to the inline controls. On small
  screens, long-press a cart item to open its editor in the Products pane.

## Pricing, persistence, and receipts

Each add-on is one real `pos.order.line` with `ne_parent_uuid` and
`ne_parent_label`. The UUID points to a parent in the same order and survives
offline storage, synchronization, and reload without requiring database IDs.
The child price is **not** added to the parent's unit price: native POS totals,
payment, taxes, fiscal positions, invoice lines, sales reports, and stock moves
already include every child once.

The sales cart and receipt group the children beneath the coffee, showing their
own quantities, amounts, tax labels, discounts, and the combined line total.
Percentage discounts applied to the parent also apply to its add-ons; newly
added portions inherit that percentage. The existing fixed-discount module's
absolute amount remains on the coffee line and is deducted once. On a variant
split, that fixed amount is allocated proportionally between the cups.

Preparation tickets use actual add-on quantities and identify the parent in
each add-on's product label. The data records aggregate portions, not which
individual cup gets each portion. Products still use their configured printer
categories.

## Refunds

The Orders/refund screen intentionally displays add-ons as individual items
with their parent label. Select the exact coffee and add-on quantities to refund;
refunding one of five cups does not infer how many of the two milk portions to
refund. When both are selected their refund lines are linked. An add-on-only
refund is also supported and retains the parent description. Backend full
refunds recreate the links for the remaining quantities. Fixed discounts are
allocated proportionally to the refunded quantities.

Odoo handles the financial and finished-product stock return. A refund does not
automatically unconsume coffee ingredients or create a new manufacturing order.

## Manufacturing integration

See [the integration module](../north_end_pos_inline_mrp/README.md). The existing
POS validation checkpoint is retained. No manufacturing occurs on a draft cart
click, so editing an unpaid cart does not leave completed production behind.

## Delivery status

Implementation and source review only. No automated tests, Odoo installation,
browser session, receipt printer, payment terminal, or branch UAT was run, as
requested. Compatibility was implemented against the official Odoo 19 source
and the custom addons in this repository; the production database was not accessed.
