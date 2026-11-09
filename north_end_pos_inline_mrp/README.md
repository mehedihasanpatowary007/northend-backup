# North End POS inline manufacturing

Integration between `north_end_pos_inline_config` and the existing
`zencore_pos_auto_mrp`. Both dependencies must be installed. The bridge
auto-installs when both are present.

For an enabled POS, the existing final order validation hook creates and
completes normal manufacturing BoMs before the standard POS delivery:

- Coffee recipe demand = net sold coffee quantity.
- Add-on recipe demand = its independent net sold quantity.
- A product is summed once across all parent and child lines, without any
  parent/child multiplier. For Latte x5 + Extra Milk x2, production is Latte x5
  and Extra Milk x2. Quantity correction lines reduce the net demand.
- Only inventory-tracked goods with a normal manufacturing BoM are produced,
  matching the existing auto-MRP product policy. Stocked products without a BoM
  and kits continue through native POS stock processing. Services do not create MOs.
- Production uses the POS warehouse and its source stock location for both
  ingredient consumption and the produced stock. Supply ingredients to that
  location; this automatic preparation flow does not wait for multi-step
  manufacturing warehouse transfers.
- Components are reserved first using Odoo's stock removal strategy. Missing
  inventory-tracked components or ingredient lots stop validation. Reserved lot
  allocations are retained when recording consumption; negative stock is not
  used to fill a component shortage.
- Ready BoM operations are completed in dependency order. Operations needing
  manual input stop the transaction. Finished goods requiring their own serial
  or lot allocation also stop this automatic flow; ingredient tracking is supported.
- A database row lock and existing linked-MO lookup prevent manufacturing again
  on a sync retry. A completed MO with a different quantity, removed product, or
  incomplete existing MO produces an actionable error instead of silently
  manufacturing another quantity.
- Production, standard POS delivery, and accounting remain in the native order
  transaction. This module adds no explicit commit and no background manufacture.
- Refund orders do not create MOs. Native POS returns apply to the finished
  product; ingredient unconsumption requires a separate explicit process.

When inline entry is disabled and an order has no linked add-ons, the original
auto-MRP implementation applies. There are no migrations of existing MOs or
historical stock/accounting records.

No tests or live Odoo execution were performed for this implementation.
