from collections import defaultdict

from odoo import _, models
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _process_saved_order(self, draft):
        # Produce before core POS creates its outgoing stock picking so the
        # newly manufactured quantity is available to that picking.
        if not draft:
            for order in self:
                if order.state != 'cancel' and not order.is_refund:
                    order._pos_auto_create_and_complete_mos()
        return super()._process_saved_order(draft)

    def _pos_auto_create_and_complete_mos(self):
        self.ensure_one()
        company = self.company_id
        warehouse = self.config_id.picking_type_id.warehouse_id
        destination = self.config_id.picking_type_id.default_location_src_id

        # Combine duplicate order lines so one order creates at most one MO
        # per product. Negative quantities and service/kit products do not
        # represent a normal manufacturing demand.
        quantities = defaultdict(float)
        products = {}
        for line in self.lines:
            product = line.product_id
            if not product or product.type != 'consu' or product.is_storable is False:
                continue
            line_uom = line.product_uom_id if 'product_uom_id' in line._fields else product.uom_id
            qty = line_uom._compute_quantity(line.qty, product.uom_id)
            if qty > 0:
                quantities[product.id] += qty
                products[product.id] = product

        # POS cashiers commonly lack MRP access rights. The automated MO and
        # its stock moves run with elevated rights, scoped to the order company.
        Bom = self.env['mrp.bom'].sudo().with_company(company)
        Production = self.env['mrp.production'].sudo().with_company(company)
        for product_id, quantity in quantities.items():
            product = products[product_id]
            bom = Bom._bom_find(product, company_id=company.id, bom_type='normal').get(product)
            if not bom:
                continue

            # Retries of the POS synchronization must not manufacture twice.
            existing = Production.search([
                ('pos_order_id', '=', self.id),
                ('product_id', '=', product.id),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if existing:
                if existing.state != 'done':
                    raise UserError(_(
                        'The Manufacturing Order %(mo)s linked to POS order %(order)s '
                        'is not complete. Resolve it before validating the POS order.',
                        mo=existing.display_name,
                        order=self.display_name,
                    ))
                continue

            vals = {
                'product_id': product.id,
                'product_qty': quantity,
                'product_uom_id': product.uom_id.id,
                'bom_id': bom.id,
                'company_id': company.id,
                'origin': self.name,
                'pos_order_id': self.id,
            }
            if warehouse and warehouse.manu_type_id:
                vals['picking_type_id'] = warehouse.manu_type_id.id
            if destination and destination.usage == 'internal':
                vals['location_dest_id'] = destination.id

            production = Production.create(vals)
            production.action_confirm()
            production.qty_producing = production.product_qty

            # Record the full BoM component demand as consumed. This preserves
            # normal stock validation; missing components still stop POS
            # validation instead of silently creating stock.
            raw_moves = production.move_raw_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
            for move in raw_moves:
                move.write({
                    'quantity': move.product_uom_qty,
                    'picked': True,
                })

            # Automatically run any BoM operations as well. Completing each
            # work order unlocks dependent operations in their normal order.
            for workorder in production.workorder_ids.sorted('sequence'):
                if workorder.state in ('ready', 'progress'):
                    workorder.button_start()
                    workorder.action_mark_as_done()

            result = production.button_mark_done()
            if isinstance(result, dict):
                raise UserError(_(
                    'Odoo could not complete Manufacturing Order %(mo)s automatically. '
                    'Review its production quantities or tracking requirements.',
                    mo=production.display_name,
                ))
            if production.state != 'done':
                raise UserError(_(
                    'Manufacturing Order %(mo)s did not reach the Done state. '
                    'Check component availability and product tracking.',
                    mo=production.display_name,
                ))
