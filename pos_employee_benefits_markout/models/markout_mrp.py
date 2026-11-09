from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare


class PosMarkout(models.Model):
    _inherit = 'pos.markout'

    mrp_production_ids = fields.One2many(
        'mrp.production', 'pos_markout_id', string='Manufacturing Orders',
        readonly=True, groups='mrp.group_mrp_user',
    )

    @api.model
    def _post_stock_moves(self, markout, category, config, company):
        if category.stock_policy == 'prepare':
            self._prepare_markout_products(markout, config, company)
        # Production consumes ingredients and puts the finished item in POS
        # stock. Issue that item once through the normal Marked Out movement.
        return super()._post_stock_moves(markout, category, config, company)

    @api.model
    def _prepare_markout_products(self, markout, config, company):
        if markout.company_id != company or markout.config_id != config:
            raise UserError(_('The Marked Out transaction and POS must use the same company and register.'))
        source = config.picking_type_id.default_location_src_id
        warehouse = config.picking_type_id.warehouse_id
        if (not source or source.usage != 'internal' or not warehouse
                or warehouse.company_id != company
                or (source.company_id and source.company_id != company)):
            raise UserError(_('Configure this POS with its company warehouse and an internal stock source before preparing Marked Out products.'))
        if not warehouse.manu_type_id or warehouse.manu_type_id.company_id != company:
            raise UserError(_('Configure the manufacturing operation type for this POS warehouse.'))

        Bom = self.env['mrp.bom'].sudo().with_company(company)
        Production = self.env['mrp.production'].sudo().with_company(company)
        for line in markout.sudo().line_ids:
            product = line.product_id.with_company(company)
            if product.type != 'consu' or not product.is_storable:
                continue
            previous = Production.search([('pos_markout_line_id', '=', line.id)])
            if previous:
                if (len(previous) != 1 or previous.state != 'done'
                        or previous.company_id != company or previous.product_id != product
                        or float_compare(
                            previous.product_uom_id._compute_quantity(previous.product_qty, product.uom_id),
                            line.quantity, precision_rounding=product.uom_id.rounding,
                        )):
                    raise UserError(_(
                        'Manufacturing for %(product)s on %(markout)s already exists with a different quantity '
                        'or is not complete. Resolve that manufacturing order before retrying.',
                        product=product.display_name, markout=markout.name,
                    ))
                line.write({'cost_unit': product.standard_price})
                continue

            bom = Bom._bom_find(product, company_id=company.id, bom_type='normal').get(product)
            if not bom:
                if Bom._bom_find(product, company_id=company.id, bom_type='phantom').get(product):
                    raise UserError(_(
                        '%s uses a kit BoM. Configure a normal manufacturing BoM before preparing '
                        'it through Marked Out.', product.display_name,
                    ))
                # Ordinary stocked goods are issued once by the parent method.
                continue
            if product.tracking != 'none':
                raise UserError(_(
                    '%s needs explicit finished-product lot or serial allocation and cannot be '
                    'prepared automatically through Marked Out.', product.display_name,
                ))

            production = Production.create({
                'product_id': product.id,
                'product_qty': line.quantity,
                'product_uom_id': product.uom_id.id,
                'bom_id': bom.id,
                'company_id': company.id,
                'origin': markout.name,
                'pos_markout_line_id': line.id,
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
                        'Not enough reserved %(product)s in %(location)s for %(markout)s. '
                        'Receive or transfer the ingredients before confirming Marked Out.',
                        product=move.product_id.display_name, location=move.location_id.display_name,
                        markout=markout.name,
                    ))
                if move.product_id.tracking != 'none' and any(
                    not item.lot_id for item in move.move_line_ids.filtered(lambda item: item.quantity > 0)
                ):
                    raise UserError(_('Reserve an ingredient lot for %s before confirming Marked Out.', move.product_id.display_name))

            # Preserve the reserved component lots. Never fill shortages by
            # setting demand as consumed before checking actual reservation.
            production.qty_producing = production.product_qty
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
                    raise UserError(_('A manufacturing operation for %s still requires manual completion.', product.display_name))
                remaining = next_remaining

            production.button_mark_done()
            if production.state != 'done':
                raise UserError(_(
                    'Manufacturing order %s needs manual input. Marked Out has not been confirmed.',
                    production.display_name,
                ))
            # AVCO/standard costing may have changed during production. The
            # final issue and Marked Out stock-cost report use the current cost.
            product.invalidate_recordset(['standard_price'])
            line.write({'cost_unit': product.standard_price})


class PosMarkoutLine(models.Model):
    _inherit = 'pos.markout.line'

    mrp_production_ids = fields.One2many(
        'mrp.production', 'pos_markout_line_id', string='Manufacturing Orders',
        readonly=True, groups='mrp.group_mrp_user',
    )


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    pos_markout_line_id = fields.Many2one(
        'pos.markout.line', string='Marked Out Item', readonly=True, copy=False,
        index=True, ondelete='restrict', check_company=True,
    )
    pos_markout_id = fields.Many2one(
        'pos.markout', related='pos_markout_line_id.markout_id', string='Marked Out',
        store=True, readonly=True, index=True, copy=False, check_company=True,
    )

    _unique_markout_line = models.Constraint(
        'unique(pos_markout_line_id)',
        'A Marked Out item can have only one manufacturing order.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(
            vals.get('pos_markout_line_id') or vals.get('pos_markout_id') for vals in vals_list
        ):
            raise AccessError(_('Marked Out manufacturing orders can only be created by the validated POS workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and {'pos_markout_line_id', 'pos_markout_id'}.intersection(vals):
            raise AccessError(_('The Marked Out source of a manufacturing order cannot be changed.'))
        return super().write(vals)

    @api.constrains('pos_markout_line_id', 'pos_markout_id', 'product_id', 'company_id')
    def _check_markout_source(self):
        for production in self:
            line = production.pos_markout_line_id
            if production.pos_markout_id and not line:
                raise ValidationError(_('A Marked Out manufacturing order must reference its source item.'))
            if line and (
                line.product_id != production.product_id or line.company_id != production.company_id
                or production.pos_markout_id != line.markout_id
            ):
                raise ValidationError(_('The manufacturing order must use the product and company of its Marked Out item.'))
