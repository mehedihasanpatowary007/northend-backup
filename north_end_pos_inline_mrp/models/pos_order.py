from collections import defaultdict

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _process_saved_order(self, draft):
        # Validate the saved UUID links before the existing MRP hook runs.
        for order in self:
            order._ne_validate_addons()
        return super()._process_saved_order(draft)

    def _pos_auto_create_and_complete_mos(self):
        self.ensure_one()
        if not self.config_id.ne_inline_enabled and not self.lines.filtered('ne_parent_uuid'):
            return super()._pos_auto_create_and_complete_mos()

        # One database transaction covers production, delivery, and accounting.
        # Serialize retries before looking up an MO; no commits or external jobs.
        self.env.cr.execute('SELECT id FROM pos_order WHERE id = %s FOR UPDATE', [self.id])
        company = self.company_id
        picking_type = self.config_id.picking_type_id
        warehouse = picking_type.warehouse_id
        source = picking_type.default_location_src_id
        if not warehouse or warehouse.company_id != company or source.usage != 'internal':
            raise UserError(_('Configure this POS with an internal stock location and its company warehouse.'))
        if source.company_id and source.company_id != company:
            raise UserError(_('The POS stock location must belong to the order company.'))

        quantities = defaultdict(float)
        products = {}
        for line in self.lines:
            product = line.product_id
            if not product or product.type != 'consu' or not product.is_storable:
                continue
            uom = line.product_uom_id if 'product_uom_id' in line._fields else product.uom_id
            quantities[product.id] += uom._compute_quantity(line.qty, product.uom_id)
            products[product.id] = product
        quantities = {product_id: max(quantity, 0) for product_id, quantity in quantities.items()}

        # Both coffee and add-ons are real lines. Their quantities are summed
        # once by product; child quantities are never multiplied by the parent.
        Bom = self.env['mrp.bom'].sudo().with_company(company)
        Production = self.env['mrp.production'].sudo().with_company(company)
        previous = Production.search([
            ('pos_order_id', '=', self.id), ('company_id', '=', company.id), ('state', '!=', 'cancel'),
        ])
        for product in previous.product_id:
            orders = previous.filtered(lambda mo: mo.product_id == product)
            produced = sum(mo.product_uom_id._compute_quantity(mo.product_qty, product.uom_id) for mo in orders)
            if any(mo.state != 'done' for mo in orders) or float_compare(
                produced, quantities.get(product.id, 0), precision_rounding=product.uom_id.rounding,
            ):
                raise UserError(_(
                    'Production for %(product)s already exists on %(order)s with a different quantity '
                    'or is incomplete. Resolve the manufacturing order before synchronizing this sale.',
                    product=product.display_name, order=self.display_name,
                ))

        for product_id, quantity in quantities.items():
            if quantity <= 0 or product_id in previous.product_id.ids:
                continue
            product = products[product_id]
            bom = Bom._bom_find(product, company_id=company.id, bom_type='normal').get(product)
            if not bom:
                continue  # Ordinary stocked products use the standard POS delivery.
            if product.tracking != 'none':
                raise UserError(_(
                    '%s requires explicit finished-product lot or serial allocation and cannot '
                    'be completed by this automatic manufacturing flow.',
                    product.display_name,
                ))
            production = Production.create({
                'product_id': product.id,
                'product_qty': quantity,
                'product_uom_id': product.uom_id.id,
                'bom_id': bom.id,
                'company_id': company.id,
                'origin': self.name,
                'pos_order_id': self.id,
                'picking_type_id': warehouse.manu_type_id.id,
                'location_src_id': source.id,
                'location_dest_id': source.id,
            })
            production.action_confirm()
            production.action_assign()
            raw_moves = production.move_raw_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
            for move in raw_moves:
                if move.product_id.is_storable and float_compare(
                    move.quantity, move.product_uom_qty, precision_rounding=move.product_uom.rounding,
                ) < 0:
                    raise UserError(_(
                        'Not enough reserved %(product)s in %(location)s for %(order)s. '
                        'Receive or transfer the ingredients before validating this POS order.',
                        product=move.product_id.display_name,
                        location=source.display_name,
                        order=self.display_name,
                    ))
                if move.product_id.tracking != 'none' and any(
                    not item.lot_id for item in move.move_line_ids.filtered(lambda item: item.quantity > 0)
                ):
                    raise UserError(_('Reserve an ingredient lot for %s before validating the POS order.', move.product_id.display_name))

            production.qty_producing = production.product_qty
            # Adjust quantities only AFTER reservation checks, preserving the
            # reserved lots and the warehouse's native removal strategy.
            production.set_qty_producing()
            for move in raw_moves:
                move.quantity = move.product_uom_qty
                move.picked = True

            remaining = production.workorder_ids.filtered(lambda work: work.state not in ('done', 'cancel'))
            while remaining:
                ready = remaining.filtered(lambda work: work.state in ('ready', 'progress'))
                if not ready:
                    raise UserError(_('Manufacturing operations for %s cannot be completed automatically.', product.display_name))
                for work in ready.sorted('sequence'):
                    if work.state != 'progress':
                        work.button_start()
                    work.action_mark_as_done()
                next_remaining = remaining.filtered(lambda work: work.state not in ('done', 'cancel'))
                if next_remaining == remaining:
                    raise UserError(_('An operation for %s still requires manual completion.', product.display_name))
                remaining = next_remaining

            production.button_mark_done()
            if production.state != 'done':
                raise UserError(_(
                    'Manufacturing order %s needs manual input. The POS sale has not been completed.',
                    production.display_name,
                ))
