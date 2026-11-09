# POS Automatic Manufacturing

For a finalized POS order, this addon finds active manufacturing BoMs for
storable products, creates one Manufacturing Order per product, consumes the
BoM quantities, and completes the MO before Odoo creates its normal POS stock
outgoing picking. The finished goods are put in the POS operation type's
source stock location so the normal POS delivery can reserve and ship them.

Draft orders, refunds, services, kits, and products without a manufacturing
BoM do not create MOs. MO processing is linked to the POS order and guarded
against duplicate manufacturing on POS synchronization retries. Insufficient
components or incomplete/tracked production stop POS validation with an error
so an order cannot silently ship unmanufactured goods.

Install this addon alongside `point_of_sale` and `mrp`, then update the Apps
list and install **POS Automatic Manufacturing**.
