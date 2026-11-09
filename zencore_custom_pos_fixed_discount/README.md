# North End POS line and global discounts — Odoo 19.0

Version: 19.0.2.0.7. This upgrades the existing `zencore_custom_pos_fixed_discount`
addon in place. It does not replace the POS screen or change the inline variant,
add-on, category, payment or manufacturing modules.

## Compact discount controls - 19.0.2.0.4

The four discount buttons share one row below the numeric keypad. Each button
keeps a visible **Line** or **Order** label with **% Discount** or the current
currency symbol plus **Fixed** underneath. Full descriptive tooltips and
accessible names explain the action. Existing Odoo colors and selected states
are retained. This update changes presentation only; discount calculations,
permissions, and keypad entry use the existing handlers.

## Payment validation hotfix - 19.0.2.0.3

Fixed payment validation failing with "Missing required value for the field
'Global Discount Type' (global_discount_type)" when no order discount was entered.
New and restored POS orders now initialize an empty discount type to `none` and
its input value to zero before the initial accounting calculation. Existing fixed
and percentage discounts are preserved.

The server also normalizes missing/empty discount types at the POS sync boundary
for older or offline clients. New orders use `none`; updates retain the saved type
unless the client explicitly sends `none` to clear it. The field stays required.

Upgrade `zencore_custom_pos_fixed_discount` and hard reload the POS assets. Keep
pending/offline orders in browser storage so they can be retried after deployment.
Regression checks cover a 630.00 order without discounts, restored fixed/percentage
discounts, and sync payloads with missing/false/empty discount types.

Validated on 2026-10-26: 319 frontend assertions using official Odoo 19 accounting
fixtures, 6 sync-boundary tests, 4 field-loader tests and 3 allocation tests.
The new regressions fail before the fix and pass afterward. Live Odoo database
payment/invoice validation has not been run in this workspace.

## Keypad and order summary layout — 19.0.2.0.2

Per the updated UI request, four direct discount buttons are grouped immediately
below the existing numeric keypad in two columns and two rows:

```text
% Line Discount   [currency] Line Fixed
% Order Discount  [currency] Order Fixed
```

The original Qty, %, Price, numeric keys, decimal, +/-, Backspace and Payment stay
available. The original % key remains a shortcut for line percentage entry.
Order buttons are no longer in the Total section. Currency labels follow the POS
currency symbol. Permissions, selected-line requirements and immediate keypad
entry are unchanged; the context label now says Order rather than Global.

With an order discount, the cart summary presents standard Subtotal / Taxes /
Total for the pre-order-discount values, then one Order Discount row, a small
final included-tax note, and the final **Grand Total**. Example: Total 570.00,
Order Discount -20.00, Grand Total 550.00. This keeps both the displayed arithmetic
and the actual discounted tax clear. Without an order discount, the standard
Odoo summary remains. Receipt tax tables retain the actual final accounting taxes.
Internal `global_discount_*` field names and all calculation/persistence logic
are unchanged. The startup field-loader hotfix below remains in place.

Checks: 293 frontend assertions including summary arithmetic, 4 field-loader tests,
3 allocation tests, JS/Python syntax, XML XPath/structure and button-placement
checks. Live POS rendering has not been verified. Deploy/upgrade the existing
module and hard reload the POS assets to view the new layout.

## POS startup hotfix — 19.0.2.0.1

Fixed the reported `TypeError: Cannot read properties of undefined (reading 'map')`
in order `setup -> _computeAllPrices`. The order loader previously appended three
custom fields to Odoo's `[]` field list. In Odoo 19, `[]` means **all fields**;
appending names instead restricts loading to only those names and removes native
order fields, including the `lines` relation, from both payload and frontend schema.

The fix preserves the empty-list sentinel in order and line loader overrides;
explicit inherited lists are extended without duplicates or parent-list mutation.
No JavaScript fallback hides incomplete order data. Discount behavior is unchanged.

The pre-fix code reproduced the exact startup exception in a regression test.
The fixed code passes 279 frontend assertions (including native accounting setup,
empty orders and restoring saved discounts), four actual field-loader method tests,
and the three existing allocation tests. Startup/frontend checks also passed using
the accounting factories from the deployed North End POS asset bundle.
Live database/browser validation on the production server has not been performed.

Deploy this updated **existing addon** to your Odoo server, restart/rebuild so the
Python changes load, upgrade `zencore_custom_pos_fixed_discount`, then hard reload
POS (Ctrl+Shift+R). On Odoo.sh, deploy the code to the intended branch and wait for
the build before upgrading the module. Updating only browser JavaScript will not
fix a Python field-loader bug. No uninstall or clearing POS browser data is needed.

Standalone regression commands:

```text
python -m unittest discover -s tests -p test_pos_field_loading.py
python -m unittest discover -s tests -p test_discount_math.py
node tests/verify_frontend.mjs .odoo19-fixtures
```

## Cashier workflow

Enable **Line Discounts / manual discounts** in the POS configuration.
Select an item, tap **Line % Discount** or **Line Fixed** below the keypad, and type
with the existing number keys. **Order % Discount** and **Order Fixed** follow in
the same row. There is no discount-selection popup or Apply button.
Every valid input updates the order; Backspace erases a digit, an empty buffer or
0 clears that discount. Negative/invalid input retains the last valid amount and
shows an inline hint. Mode changes start a fresh number buffer. Choosing another
global mode retains the previous valid discount until its first numeric input,
then replaces it; global modes never stack. The Editing label shows the context
and effective value. The standard selected-line highlight remains in use.

Line discounts are calculated first: percentage, then a **whole-line fixed amount**.
The fixed amount is the exact customer-facing gross reduction, including its tax
effect, and is capped at the line's remaining tax-included total. Existing percentage
propagation to independent add-on lines is retained. Neither discount changes an
add-on quantity. Line percentage and fixed amounts can coexist as before.
Global discount does not overwrite either line field.

Discounts use existing manual-discount and cashier-role permissions. An installed
restriction of `restrictLineDiscountChange()` disables direct entry rather than
bypassing its restriction. Once payment lines exist, return and remove them before
editing discounts. Refund discount entry is locked and inherits the original sale.
No new PIN policy is introduced.

## Calculation, tax and accounting

All positive sale contributions, including independently counted add-ons, are
eligible by default. Negative return lines reverse the source allocation and do
not receive another new global discount. There are no product-category exclusions.
Mixed sale/return orders discount positive eligible contributions only.

Line fixed amounts are converted through Odoo's tax engine so entering 20 reduces
the customer total by 20, rather than reducing the pre-tax base by 20 and then
changing the tax on top. Line discounts are computed first. One global amount is
allocated over eligible post-line gross contributions in integer currency units by
largest remainder;
UUID order breaks ties consistently in JS and Python. Percentage follows cart
changes, while fixed input remains unchanged and the effective amount is capped.
The real Odoo tax engine inverts each target gross to the native tax price basis.
It retains actual product taxes, fiscal-position mapping, tax tags, accounts and
configured rounding. Included, excluded, grouped, compound, division, fixed, zero
and exempt tax configurations use the engine, never hard-coded tax percentages.
If a special tax configuration cannot reconcile its target gross, entry is safely
rejected instead of accepting inconsistent totals.

Product display amounts remain **before global discount**, with existing line
reductions visible. Cart and full receipt disclose one Global Discount row. Saved
line subtotals, tax bases, payment totals, invoices and closing entries use the
adjusted prices. Invoice line notes disclose the order discount; they post no
additional amount. This implements **net revenue**, with an optional separate
global-discount measure in the POS sales report, not a second contra-revenue entry.

Global type, input, amount and internal signed line allocations are server fields
loaded by POS and stored by Odoo's native related-model serialization/offline
storage. Before processing a saved order, the server recalculates allocations,
taxes and subtotals; client-computed totals/allocations are not authoritative.
Source allocations are stored for returns. Partial returns use cumulative rounded
shares, with the final return receiving remaining discount cents. Original line
fixed discounts are copied proportionally. Odoo's configured tax rounding still
applies on each refund document.

## Upgrade

1. Back up the database and test on a staging copy with the customer's installed
   Odoo **19.0** source and addons. Keep all existing North End modules installed.
2. Ensure this module directory is in the server's addons path.
3. Stop the normal Odoo service, then upgrade (replace YOUR_DB and config path):

   `odoo-bin -c /path/to/odoo.conf -d YOUR_DB -u zencore_custom_pos_fixed_discount --stop-after-init`

4. Restart Odoo. Reload POS assets with a hard refresh after synchronizing pending
   offline orders. Enable manual discounts if disabled. No new module installation
   or discount product is required.

## Checks and tests

Executed locally on 2026-10-22:
- Node harness: 293 assertions using official Odoo 19 tax engine, accounting classes,
  patch and rounding utilities, plus real addon input handlers. ORM and UI services
  are lightweight stubs; this is not a live browser/DB test.
- Python allocation suite: 3 tests, including deterministic residuals and caps.
- Python POS field-loader suite: 4 tests preserving core fields, relations and the all-fields sentinel.
- Python/JavaScript parsing and XML extension validation against upstream templates.

Reproduce from this addon directory:

```text
python -m unittest discover -s tests -p test_discount_math.py
python tests/test_pos_field_loading.py
python tests/test_pos_order_sync.py
python tests/fetch_odoo_fixtures.py
node tests/verify_frontend.mjs .odoo19-fixtures
```

The upstream fixture fetch follows the official 19.0 branch, so results must be
rechecked against the **actual deployed build** before rollout.

Odoo integration tests are included for server totals, tampered client totals,
invoice posting, tax tags/session closing and partial refunds. They require a
configured Odoo 19 installation and an isolated test database:

```text
odoo-bin -c /path/to/odoo.conf -d TEST_DB -u zencore_custom_pos_fixed_discount --test-enable --test-tags north_end_discount --stop-after-init
```

**Not run locally:** Odoo database/ORM tests, asset bundle compilation in Odoo,
rendered touchscreen UI, POS reload/offline synchronization, actual invoices,
refund documents, session closing, tax reports and POS-to-MO regressions. No Odoo
server or PostgreSQL runtime was available in this workspace. These are required
staging checks; this delivery is not declared production-ready.

## Staging acceptance

- 210 @ included 5% plus 360 @ included 7%, Global Fixed 20: total 550,
  tax 9.65 + 22.73.
- Same order, Global 10%: total 513, tax 9.00 + 21.20.
- First item Line 10%, then Global Fixed 20: total 529, tax 8.67 + 22.69.
- Test fixed line + global %, zero/100%/over-limit inputs, mode changes, Backspace,
  no selected line, Payment, permissions, variants and independent add-on counts.
- Verify cart/receipt/payment/saved order/invoice/closing equality; tax tags and
  fiscal-position mapping; full and partial returns, cancelled returns and rounding.
- Verify reload/offline sync/order switching, mobile touchscreen layout and
  POS-to-MO/add-on BoM regression with the customer's other addons installed.
- Finance approves tax treatment, net-revenue presentation, eligibility and
  receipt/legal reporting before go-live.

## Upstream references inspected

- https://github.com/odoo/odoo/tree/19.0/addons/point_of_sale
- https://github.com/odoo/odoo/blob/19.0/addons/account/static/src/helpers/account_tax.js
- https://github.com/odoo/odoo/blob/19.0/addons/account/models/account_tax.py
