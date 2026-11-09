from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if self.env.context.get('intercompany_transfer_form'):
            company = self.env.company
            if 'picking_type_id' in fields_list and not vals.get('picking_type_id'):
                operation = self.env['stock.picking.type'].search([
                    ('company_id', '=', company.id), ('code', '=', 'internal'),
                ], order='sequence, id', limit=1)
                if operation:
                    vals['picking_type_id'] = operation.id
                    if 'location_id' in fields_list and operation.default_location_src_id:
                        vals['location_id'] = operation.default_location_src_id.id
            if 'location_dest_id' in fields_list and not vals.get('location_dest_id'):
                vals['location_dest_id'] = self.env.ref('stock.stock_location_inter_company').id
        return vals

    @api.onchange('partner_id', 'picking_type_id')
    def _onchange_intercompany_defaults(self):
        for picking in self:
            if picking.picking_type_id.code != 'internal':
                continue
            destination = self.env['res.company'].search([
                ('partner_id', '=', picking.partner_id.commercial_partner_id.id),
            ], limit=1) if picking.partner_id else self.env['res.company']
            if destination and destination != picking.company_id:
                picking.location_dest_id = self.env.ref('stock.stock_location_inter_company')

    destination_company_id = fields.Many2one(
        'res.company', compute='_compute_intercompany', compute_sudo=True,
        string='Receiving Company', store=True,
    )
    is_intercompany_transfer = fields.Boolean(compute='_compute_intercompany', compute_sudo=True, store=True)
    source_intercompany_picking_id = fields.Many2one(
        'stock.picking', string='Source Transfer', copy=False, readonly=True,
        index=True, ondelete='restrict', check_company=False,
    )
    # Only the first receiving picking has this field; backorders share the source link above.
    intercompany_root_source_id = fields.Many2one(
        'stock.picking', copy=False, readonly=True, index=True,
        ondelete='restrict', check_company=False,
    )
    destination_intercompany_picking_ids = fields.One2many(
        'stock.picking', 'source_intercompany_picking_id', string='Receiving Transfers',
        readonly=True,
    )
    intercompany_reference = fields.Char(copy=False, readonly=True, index=True)
    intercompany_status = fields.Selection([
        ('ready', 'Draft / Ready'), ('transit', 'In Transit'),
        ('received', 'Received / Done'), ('cancel', 'Cancelled'),
    ], compute='_compute_intercompany_status', compute_sudo=True, string='Inter-Company Status')

    _unique_intercompany_receipt = models.Constraint(
        'UNIQUE(intercompany_root_source_id)',
        'A source transfer can generate only one initial receiving operation.',
    )

    @api.depends('partner_id', 'company_id', 'picking_type_id', 'source_intercompany_picking_id')
    def _compute_intercompany(self):
        for picking in self:
            company = self.env['res.company']
            if picking.partner_id and picking.picking_type_id.code == 'internal':
                company = self.env['res.company'].search([
                    ('partner_id', '=', picking.partner_id.commercial_partner_id.id),
                ], limit=1)
            picking.destination_company_id = company if company != picking.company_id else False
            picking.is_intercompany_transfer = bool(
                picking.source_intercompany_picking_id or picking.destination_company_id
            )

    @api.depends('state', 'is_intercompany_transfer', 'source_intercompany_picking_id',
                 'move_ids.state', 'move_ids.quantity',
                 'destination_intercompany_picking_ids.move_ids.state',
                 'destination_intercompany_picking_ids.move_ids.quantity')
    def _compute_intercompany_status(self):
        for picking in self:
            source = picking.source_intercompany_picking_id or picking
            if not picking.is_intercompany_transfer:
                picking.intercompany_status = False
            elif source.state == 'cancel':
                picking.intercompany_status = 'cancel'
            elif source.state != 'done':
                picking.intercompany_status = 'ready'
            else:
                sent = source.move_ids.filtered(lambda m: m.state == 'done' and m.ict_sent_quantity)
                received = self.env['stock.move'].search([
                    ('ict_source_move_id', 'in', sent.ids), ('state', '=', 'done'),
                ])
                quantities = defaultdict(float)
                for move in received:
                    quantities[move.ict_source_move_id.id] += move._get_valued_qty()
                complete = bool(sent) and all(float_compare(
                    quantities[m.id], m.ict_sent_quantity,
                    precision_rounding=m.product_id.uom_id.rounding,
                ) >= 0 for m in sent)
                picking.intercompany_status = 'received' if complete else 'transit'

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'source_intercompany_picking_id', 'intercompany_root_source_id', 'intercompany_reference'}
        if not self.env.su and any(any(vals.get(key) for key in protected) for vals in vals_list):
            raise AccessError(_('Inter-company links are generated automatically.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and {'source_intercompany_picking_id', 'intercompany_root_source_id', 'intercompany_reference'} & vals.keys():
            raise AccessError(_('Inter-company links cannot be changed manually.'))
        operational = {'company_id', 'partner_id', 'picking_type_id', 'location_id', 'location_dest_id'}
        if 'state' in vals and vals['state'] != 'done' and any(p.state == 'done' and p.is_intercompany_transfer for p in self):
            raise UserError(_('Completed inter-company transfers cannot be reopened. Use a Return.'))
        if operational & vals.keys():
            for picking in self.filtered('is_intercompany_transfer'):
                if picking.state == 'done' or picking.source_intercompany_picking_id:
                    if any(picking[key].id != vals[key] for key in operational & vals.keys()):
                        raise UserError(_('The companies and locations of a linked transfer cannot be changed.'))
        return super().write(vals)

    def _ict_check_configuration(self):
        self.ensure_one()
        if not self.is_intercompany_transfer:
            if self.location_dest_id == self.env.ref('stock.stock_location_inter_company'):
                raise UserError(_('Select the receiving company\'s contact for this shared transit transfer.'))
            return
        if self.picking_type_id.code != 'internal':
            raise UserError(_('Inter-company transfers must use an Internal Transfer operation.'))
        if self.source_intercompany_picking_id:
            source = self.source_intercompany_picking_id.sudo()
            if source.state != 'done' or source.destination_company_id != self.company_id:
                raise UserError(_('The source must be dispatched to this company before receiving.'))
            if self.location_id != source.location_dest_id or self.location_dest_id.company_id != self.company_id or self.location_dest_id.usage != 'internal':
                raise UserError(_('The receipt must move from the original transit location into this company\'s stock.'))
            companies = self.company_id
        else:
            if self.location_id.usage != 'internal' or self.location_id.company_id != self.company_id:
                raise UserError(_('The source must be an internal stock location of the sending company.'))
            if self.location_dest_id.usage != 'transit' or self.location_dest_id.company_id:
                raise UserError(_('Choose a shared transit location with no company.'))
            companies = self.company_id | self.destination_company_id
        for company in companies.sudo():
            company = company.with_company(company)
            account = company.in_transit_valuation_account_id
            operation = company.intercompany_receipt_type_id
            if not account or not operation or not company.account_stock_journal_id:
                raise UserError(_('Configure the transit account, receiving operation and standard Stock Journal for %s.', company.name))
            company._check_intercompany_configuration()
            if not account.active or not operation.active:
                raise UserError(_('The inter-company account and receiving operation must be active.'))
            for product in self.move_ids.product_id.sudo().with_company(company):
                valuation = product._get_product_accounts().get('stock_valuation')
                if not product.is_storable or product.company_id:
                    raise UserError(_('Inter-company transfers require shared, inventory-tracked products: %s.', product.display_name))
                if not valuation:
                    raise UserError(_('No Inventory Valuation Account is configured for %s in %s. Set it on the product category while that company is active.', product.display_name, company.name))
                if valuation == account:
                    raise UserError(_('Inventory account %s and In-Transit account cannot be the same in %s.', valuation.display_name, company.name))
        if self.owner_id or any(self.move_line_ids.mapped('owner_id')):
            raise UserError(_('Consigned stock cannot be used in an inter-company transfer.'))
        if any(self.move_line_ids.lot_id.mapped('company_id')):
            raise UserError(_('Use shared lots/serial numbers (Company left empty) for inter-company transfers.'))
        for line in self.move_line_ids:
            if line.location_id != self.location_id or line.location_dest_id != self.location_dest_id:
                raise UserError(_('Detailed operation locations must match this inter-company transfer.'))
            if line.result_package_id:
                raise UserError(_('Unpack inter-company goods before dispatch/receipt; destination packages must be empty.'))
        for move in self.move_ids.filtered(lambda m: m.state != 'cancel'):
            if move.location_id != self.location_id or move.location_dest_id != self.location_dest_id:
                raise UserError(_('Stock move locations must match the inter-company transfer.'))
            if move.quantity < 0 or any(line.quantity < 0 for line in move.move_line_ids):
                raise UserError(_('Inter-company quantities must be positive. Use a Return for returned goods.'))

    def _action_done(self):
        self.check_access('write')
        if self.ids:
            # Serialize retries; the SQL uniqueness constraint also protects initial receipt creation.
            self.env.cr.execute('SELECT id FROM stock_picking WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.invalidate_recordset(['state'])
        pending = self.filtered(lambda p: p.state not in ('done', 'cancel'))
        for picking in pending:
            picking._ict_check_configuration()
        result = super(StockPicking, pending)._action_done() if pending else True
        for picking in pending.filtered(lambda p: p.is_intercompany_transfer and not p.source_intercompany_picking_id and p.state == 'done'):
            picking._ict_create_receipt()
        return result

    def _ict_create_receipt(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError(_('Only a dispatched transfer can generate a receipt.'))
        source = self.sudo()
        existing = self.env['stock.picking'].sudo().search([('intercompany_root_source_id', '=', self.id)], limit=1)
        if existing:
            return existing
        company = source.destination_company_id
        operation = company.intercompany_receipt_type_id
        reference = source.intercompany_reference or self.env['ir.sequence'].sudo().next_by_code('zencore.intercompany.transfer')
        source.intercompany_reference = reference
        # Narrow automatic cross-company operation. No broad user ACLs are added.
        target_env = self.env['stock.picking'].sudo().with_company(company).with_context(
            allowed_company_ids=[company.id], mail_create_nosubscribe=True,
        )
        receipt = target_env.create({
            'picking_type_id': operation.id, 'company_id': company.id,
            'partner_id': source.company_id.partner_id.id,
            'location_id': source.location_dest_id.id,
            'location_dest_id': operation.default_location_dest_id.id,
            'origin': source.name, 'scheduled_date': source.scheduled_date,
            'source_intercompany_picking_id': source.id,
            'intercompany_root_source_id': source.id,
            'intercompany_reference': reference,
        })
        for move in source.move_ids.filtered(lambda m: m.state == 'done' and m.quantity > 0):
            quantity = move._get_valued_qty()
            if not quantity:
                raise UserError(_('The dispatched stock must have a valued quantity.'))
            move.write({'ict_sent_quantity': quantity, 'ict_sent_value': move.value})
            converted = source.company_id.currency_id._convert(
                move.value, company.currency_id, company, fields.Date.to_date(source.date_done),
            )
            incoming = receipt.env['stock.move'].create({
                'picking_id': receipt.id, 'company_id': company.id,
                'product_id': move.product_id.id, 'product_uom': move.product_uom.id,
                'product_uom_qty': move.quantity,
                'location_id': receipt.location_id.id, 'location_dest_id': receipt.location_dest_id.id,
                'ict_source_move_id': move.id, 'ict_receipt_total_value': converted,
                'origin': reference,
            })
            incoming._action_confirm(merge=False)
            # Supply the dispatched tracking, rather than letting automatic reservation choose other lots.
            incoming.move_line_ids.unlink()
            for line in move.move_line_ids.filtered(lambda line: line.picked and line.quantity > 0):
                receipt.env['stock.move.line'].create({
                    'move_id': incoming.id, 'picking_id': receipt.id, 'company_id': company.id,
                    'product_id': line.product_id.id, 'product_uom_id': line.product_uom_id.id,
                    'quantity': line.quantity, 'lot_id': line.lot_id.id,
                    'package_id': line.result_package_id.id,
                    'location_id': receipt.location_id.id, 'location_dest_id': receipt.location_dest_id.id,
                })
        return receipt

    def _create_backorder_picking(self):
        backorder = super()._create_backorder_picking()
        if self.source_intercompany_picking_id:
            backorder.sudo().write({
                'source_intercompany_picking_id': self.source_intercompany_picking_id.id,
                'intercompany_reference': self.intercompany_reference,
            })
        return backorder

    def action_cancel(self):
        for picking in self.filtered('is_intercompany_transfer'):
            if picking.state == 'done' or picking.source_intercompany_picking_id:
                raise UserError(_('Dispatched goods must be received and returned using the Return operation. Linked receipts cannot be cancelled.'))
        return super().action_cancel()

    @api.ondelete(at_uninstall=False)
    def _ict_protect_picking(self):
        if any(p.source_intercompany_picking_id or (p.is_intercompany_transfer and p.state == 'done') for p in self):
            raise UserError(_('Linked inter-company transfers cannot be deleted.'))

    def action_view_intercompany_transfers(self):
        self.ensure_one()
        source_id = self.source_intercompany_picking_id.id or self.id
        return {
            'type': 'ir.actions.act_window', 'name': _('Linked Inter-Company Transfers'),
            'res_model': 'stock.picking', 'view_mode': 'list,form',
            'domain': ['|', ('id', '=', source_id), ('source_intercompany_picking_id', '=', source_id)],
        }
