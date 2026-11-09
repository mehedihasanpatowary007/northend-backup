# POS Employee Benefits & Marked Out

Odoo 19 addon for zero-payment staff benefits and operational/corporate usage.
It records a separate immutable Marked Out transaction; no paid POS order,
customer invoice, tender or payment is created. Manufacturing and inventory use
native Odoo moves and their normal valuation behavior.

## Setup and upgrade to 19.0.2.0.1

Upgrade **POS Employee Benefits & Marked Out** and reload POS with Ctrl + Shift + R.
The addon now depends on native Manufacturing (`mrp`) as well as POS, Employees
and Inventory. No separate bridge addon is needed.

The upgrade switches the seeded fresh-use subcategories from Needs Stock Setup
or the old Reduce POS Stock mode to **Prepare Product (MO + Consumption)**.
Existing explicit No Stock Movement/Return modes and custom categories retain
their configuration. Expired/Damage and Returned/Wrong Orders are not switched
to manufacturing. Historical Marked Out transactions are never manufactured
retroactively. The obsolete employee mapping view is removed only when present,
so missing legacy XML IDs do not generate upgrade warnings.

## Inventory and manufacturing

Main-category icons are configurable at **Point of Sale → Marked Out → Setup →
Categories → main category → Icon**. Select People, Coffee, Office, Food,
Training, Gift or another listed icon and save, then reopen Marked Out in POS.
New categories default to Gift; upgrades preserve the original three tab icons.

Open **Point of Sale → Marked Out → Setup → Categories**. Main categories contain
subcategories; each subcategory has one **Inventory Flow**:

- **Prepare Product (MO + Consumption)** is the default for fresh usage. For an
  inventory-tracked product with a normal manufacturing BoM, confirmation creates
  and completes an MO using the POS warehouse's manufacturing operation and POS
  source location. Ingredients are reserved and consumed there. The finished
  product is then issued from that location once. This is one integrated flow;
  there is no second raw-material deduction.
- Products without a manufacturing BoM are issued from existing stock. Services
  do not create inventory moves or MOs. Combo products, kit BoMs in preparation,
  and finished products requiring lot/serial allocation are not supported by
  this automatic flow. Ingredient lots must already be reservable.
- The fresh-use destination defaults to the product's company-specific
  Inventory Loss location. A category destination is an optional override.
- **Write Off Existing Stock** handles products already made, such as expired
  or damaged items. It never manufactures another unit and requires an approved
  Inventory Loss location.
- **Return Existing Stock** moves existing items from the approved non-internal
  source back into POS stock. It never creates an MO.
- **No Stock Movement** deliberately records usage without inventory effects.

Configure the same finished-product inventory tracking, recipes, ingredient
stock and POS warehouse/source used for normal POS manufacturing. Independent
add-on quantities are counted once, not multiplied by parent cup quantities.
Shortages or operations needing manual input stop confirmation. The transaction,
MO completion, final issue and benefit reservation share one database transaction.
A failed confirmation leaves none of these partially committed.

Manufacturing Orders appear on **Marked Out → Transactions → transaction** for
users with Manufacturing access. Each MO links to its source Marked Out item.
UUID retry protection and unique source-item links prevent repeated confirmation
from producing or consuming twice.

## Employee-specific benefits

An authorized administrator opens **Employees → employee → POS Benefits**.
Add an allowance with:

1. Benefit name and Marked Out subcategory.
2. Exact eligible products/variants.
3. **Daily Quantity**, business timezone (for example `Asia/Dhaka`), and scope:
   across company POS registers or separately per register.
4. **Active** enabled.

Use one rule per product for independent limits. For example, Employee A can
have Latte = 2/day and Sandwich = 1/day, while Employee B has Latte = 1/day.
Multiple variants in one rule share that rule's daily quantity pool.

The same rules are available at **Point of Sale → Marked Out → Setup → Benefit
Rules**. Leaving **Employee** blank creates a default for all employees. An
employee-specific rule replaces the default for its matching products. Use only
employee-specific rules when entitlement must be explicitly assigned to named
employees. Rules for different employees may have different quantities.

Every product under Employee / Staff Benefit needs an applicable active rule;
unconfigured products cannot bypass quotas. Other operational subcategories are
unrestricted unless benefit rules are configured for them. Category product
allowlists still apply. Selection checks whether the employee has eligible
products; confirmation rechecks entitlement, product and remaining quantity on
the server. Earlier consumption on the same business day still counts when a
new employee-specific rule replaces a default. Simultaneous requests for the
same employee serialize through a database row update.

**Benefit Usage** shows employee use and remaining daily allowance. Original
usage audit snapshots remain immutable.

## Cashier access and employee identity

At **Settings → Users → cashier → POS Marked Out Access**, grant Create / Confirm
and the permitted subcategories. View, category/benefit management and reporting
are separate permissions. Employee allowance administration still requires
**Manage Categories / Benefit Rules** or administrator rights. The POS Benefits
employee tab is visible to HR/POS managers with access to employee records.
Cashier category access controls who may operate Marked Out; the employee's
benefit rules control who may receive each product and how much.

Allowances apply to the exact product variant. An allowance for Regular does
not permit Medium. Confirmation gives a short message naming the employee and
requested variant instead of the generic RPC label "Odoo Server Error". Quota
errors also show concise guidance. Other server failures show a shortened
one-line cause without a traceback.
The server checks allowances before creating the transaction, manufacturing
orders or stock movements. A rejected variant does not consume benefits or stock;
the cart remains available for correction.

Stock issue moves use Odoo 19's native product description and Marked Out source
reference; Odoo 19 `stock.move` has no `name` field.
Standalone issue/return moves explicitly set `reference` as well as `origin`
before valuation. Native Odoo does not derive a move's reference from origin;
without a picking or scrap document it would otherwise be empty, causing a
boolean/string error when stock accounting builds journal labels.

Use the employee's native Odoo Badge ID (`hr.employee.barcode`) and Work Contact
(`work_contact_id`). No extra badge or customer mapping is needed. The active
company-compatible Work Contact is assigned to the POS cart automatically.
PINs and private HR fields are not returned by the employee search.

## POS flow and presentation

Marked Out opens one screen with category tabs, subcategories and a default
employee list. Choose a subcategory, then select an eligible employee once to
open the zero-payment cart. Selecting an employee without a subcategory prompts
for one. There is no Continue button. Add products and Confirm Marked Out.

The UI retains Odoo colors. Customer, Marked Out and Order Note use compact
icons in the register; the Actions popup uses full-size labeled grid tiles.
Cart UUIDs preserve recovery after a lost response. Unconfirmed carts can be
cancelled without creating manufacturing, inventory or usage records.

Use **Transactions**, **Item Analysis** and **Benefit Usage** for audit and
reporting. Cost details are restricted to POS managers. Confirmed records are
immutable; Reverse Marked Out remains reserved and disabled.

No live Odoo test suite or printer run was performed, following the requested
development preference. Source syntax, XML and manifest references are checked.
