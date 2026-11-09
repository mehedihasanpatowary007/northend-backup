from collections import defaultdict

from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

_VALUATION_TOKEN = object()
_BACKORDER_TOKEN = object()


class StockMove(models.Model):
    _inherit = 'stock.move'

    ict_source_move_id = fields.Many2one(
        'stock.move', copy=False, readonly=True, index=True, ondelete='restrict', check_company=False,
    )
    ict_sent_quantity = fields.Float(copy=False, readonly=True, digits='Product Unit')
    ict_sent_value = fields.Monetary(copy=False, readonly=True, currency_field='company_currency_id')
    ict_receipt_total_value = fields.Monetary(copy=False, readonly=True, currency_field='company_currency_id')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(any(v.get(k) for k in self._ict_protected_fields()) for v in vals_list):
            raise AccessError(_('Inter-company valuation and links are generated automatically.'))
        return super().create(vals_list)

    @api.model
    def _ict_protected_fields(self):
        return {'ict_source_move_id', 'ict_sent_quantity', 'ict_sent_value', 'ict_receipt_total_value'}

    def write(self, vals):
        if not self.env.su and self._ict_protected_fields() & vals.keys():
            raise AccessError(_('Inter-company valuation and links cannot be changed manually.'))
        frozen = {'product_id', 'product_uom', 'quantity', 'product_uom_qty', 'value', 'value_manual',
                  'company_id', 'location_id', 'location_dest_id', 'picking_id', 'state'}
        identity = {'product_id', 'product_uom', 'company_id', 'location_id', 'location_dest_id'}
        for move in self.filtered('ict_source_move_id'):
            if any(move[key].id != vals[key] for key in identity & vals.keys()):
                raise UserError(_('A linked receipt must retain its product, unit, company and locations.'))
            if 'product_uom_qty' in vals and move.product_uom_qty != vals['product_uom_qty']:
                if self.env.context.get('_ict_backorder_token') is not _BACKORDER_TOKEN:
                    raise UserError(_('Change the received quantity; the dispatched demand is preserved on a backorder.'))
            if 'picking_id' in vals and move.picking_id.id != vals['picking_id']:
                target = self.env['stock.picking'].browse(vals['picking_id'])
                if target.source_intercompany_picking_id != move.picking_id.source_intercompany_picking_id:
                    raise UserError(_('Receipt moves may only be moved to their own receiving backorders.'))
        for move in self.filtered(lambda m: m.state == 'done' and m.picking_id.is_intercompany_transfer):
            for key in frozen & vals.keys():
                if key == 'value' and self.env.context.get('_ict_valuation_token') is _VALUATION_TOKEN:
                    continue
                old = move[key].id if move._fields[key].type == 'many2one' else move[key]
                if old != vals[key]:
                    raise UserError(_('Completed inter-company stock and valuation are locked. Use a physical Return.'))
        return super().write(vals)

    def _split(self, qty, restrict_partner_id=False):
        vals_list = super()._split(qty, restrict_partner_id=restrict_partner_id)
        # _create_backorder below creates these under a narrow privileged context.
        for vals in vals_list:
            vals.update({
                'ict_source_move_id': self.ict_source_move_id.id,
                'ict_receipt_total_value': self.ict_receipt_total_value,
            })
        return vals_list

    def _create_backorder(self):
        linked = self.filtered('ict_source_move_id')
        ordinary = self - linked
        result = super(StockMove, ordinary)._create_backorder() if ordinary else self.env['stock.move']
        if linked:
            trusted = linked.sudo().with_context(_ict_backorder_token=_BACKORDER_TOKEN)
            result |= super(StockMove, trusted)._create_backorder().with_env(self.env)
        return result

    def _prepare_merge_moves_distinct_fields(self):
        return super()._prepare_merge_moves_distinct_fields() + ['ict_source_move_id']

    def _skip_push(self):
        return bool(self.picking_id.is_intercompany_transfer) or super()._skip_push()

    def _ict_check_receipt_quantities(self):
        incoming = self.filtered(lambda m: m.ict_source_move_id and m.state not in ('done', 'cancel'))
        sources = incoming.sudo().ict_source_move_id
        if not sources:
            return
        self.env.cr.execute('SELECT id FROM stock_move WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(sources.ids))])
        for source in sources:
            done = self.env['stock.move'].sudo().search([
                ('ict_source_move_id', '=', source.id), ('state', '=', 'done'),
            ])
            current = incoming.filtered(lambda m: m.ict_source_move_id.id == source.id)
            quantities = defaultdict(float)
            allowed = defaultdict(float)
            for line in source.move_line_ids:
                allowed[line.lot_id.id] += line.quantity_product_uom
            for move in done | current.sudo():
                if move.product_id != source.product_id or move.company_id != source.picking_id.destination_company_id:
                    raise UserError(_('A receipt must retain the dispatched product and destination company.'))
                for line in move.move_line_ids.filtered('picked'):
                    quantities[line.lot_id.id] += line.quantity_product_uom
            for lot, quantity in quantities.items():
                if float_compare(quantity, allowed[lot], precision_rounding=source.product_id.uom_id.rounding) > 0:
                    raise UserError(_('You cannot receive more than dispatched, or receive a different lot/serial number.'))

    def _action_done(self, cancel_backorder=False):
        pending = self.filtered(lambda m: m.state not in ('done', 'cancel'))
        for picking in pending.picking_id.filtered('is_intercompany_transfer'):
            picking._ict_check_configuration()
            if picking.source_intercompany_picking_id and any(not m.ict_source_move_id for m in picking.move_ids if m.state != 'cancel'):
                raise UserError(_('Products cannot be added to an automatically generated receipt.'))
            if cancel_backorder and picking.source_intercompany_picking_id:
                for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                    if move.product_uom.compare(move.quantity if move.picked else 0, move.product_uom_qty) < 0:
                        raise UserError(_('Keep the backorder for goods that are still in transit.'))
        pending._ict_check_receipt_quantities()
        pending._ict_check_return_quantities()
        return super(StockMove, pending)._action_done(cancel_backorder=cancel_backorder)

    def _ict_check_return_quantities(self):
        returns = self.filtered(lambda m: m.picking_id.is_intercompany_transfer and m.origin_returned_move_id)
        originals = returns.origin_returned_move_id
        if not originals:
            return
        self.env.cr.execute('SELECT id FROM stock_move WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(originals.ids))])
        for original in originals:
            if original.state != 'done' or not original.ict_source_move_id:
                raise UserError(_('Return inter-company goods from their completed receiving operation.'))
            completed = self.sudo().search([('origin_returned_move_id', '=', original.id), ('state', '=', 'done')])
            current = returns.filtered(lambda m: m.origin_returned_move_id == original)
            allowed, returned = defaultdict(float), defaultdict(float)
            for line in original.move_line_ids:
                allowed[line.lot_id.id] += line.quantity_product_uom
            for move in completed | current.sudo():
                if move.product_id != original.product_id or move.company_id != original.company_id:
                    raise UserError(_('Return the original product from the receiving company.'))
                for line in move.move_line_ids.filtered('picked'):
                    returned[line.lot_id.id] += line.quantity_product_uom
            if any(float_compare(qty, allowed[lot], precision_rounding=original.product_id.uom_id.rounding) > 0 for lot, qty in returned.items()):
                raise UserError(_('Returned quantities and lots cannot exceed the original receipt.'))

    def _get_value_data(self, forced_std_price=False, at_date=False, ignore_manual_update=False, add_extra_value=True):
        if self.ict_source_move_id:
            source = self.ict_source_move_id.sudo()
            quantity = self._get_valued_qty()
            value = self.ict_receipt_total_value * quantity / source.ict_sent_quantity if source.ict_sent_quantity else 0
            # Give the last receipt the rounding remainder, keeping the posted total exact.
            previous = self.sudo().search([
                ('ict_source_move_id', '=', source.id), ('state', '=', 'done'), ('id', '!=', self.id),
            ])
            previous_qty = sum(m._get_valued_qty() for m in previous)
            if float_compare(previous_qty + quantity, source.ict_sent_quantity,
                             precision_rounding=source.product_id.uom_id.rounding) == 0:
                value = self.ict_receipt_total_value - sum(previous.mapped('value'))
            return {'value': self.company_currency_id.round(value), 'quantity': quantity,
                    'description': _('Original inter-company dispatch: %s', source.picking_id.intercompany_reference)}
        return super()._get_value_data(forced_std_price, at_date, ignore_manual_update, add_extra_value)

    def _set_value(self, correction_quantity=None):
        if any(m.state == 'done' and (m.account_move_id or m.ict_sent_quantity) and m.picking_id.is_intercompany_transfer for m in self):
            raise UserError(_('Dispatched inter-company valuation is locked. Use a Return.'))
        trusted = self.with_context(_ict_valuation_token=_VALUATION_TOKEN)
        result = super(StockMove, trusted)._set_value(correction_quantity=correction_quantity)
        for move in self.filtered(lambda m: m.picking_id.is_intercompany_transfer and m.origin_returned_move_id and m._is_out()):
            original = move.origin_returned_move_id
            quantity = original._get_valued_qty()
            if quantity:
                move.value = original.value * move._get_valued_qty() / quantity
        return result

    def _create_account_move(self):
        intercompany = self.filtered(lambda m: m.picking_id.is_intercompany_transfer)
        ordinary = self - intercompany
        result = super(StockMove, ordinary)._create_account_move() if ordinary else self.env['account.move']
        for move in intercompany.sudo():
            if move.account_move_id or move.state != 'done' or not move.is_valued:
                continue
            move = move.with_company(move.company_id)
            inventory = move.product_id._get_product_accounts()['stock_valuation']
            transit = move.company_id.in_transit_valuation_account_id
            debit, credit = (inventory, transit) if move.is_in else (transit, inventory)
            amount = move.company_currency_id.round(move.value)
            if move.company_currency_id.is_zero(amount):
                continue
            entry = move.env['account.move'].create({
                'move_type': 'entry', 'company_id': move.company_id.id,
                'journal_id': move.company_id.account_stock_journal_id.id,
                'date': fields.Date.context_today(move), 'ref': move.picking_id.name,
                'ict_picking_id': move.picking_id.id,
                'line_ids': [Command.create({
                    'account_id': account.id, 'balance': balance,
                    'product_id': move.product_id.id, 'name': move.reference,
                }) for account, balance in [(debit, amount), (credit, -amount)]],
            })
            move.account_move_id = entry
            entry._post()
            result |= entry.with_env(self.env)
        return result

    def _action_cancel(self):
        if any(m.ict_source_move_id for m in self):
            raise UserError(_('Goods in transit must remain on a receiving backorder until received.'))
        return super()._action_cancel()

    @api.ondelete(at_uninstall=False)
    def _ict_protect_linked_moves(self):
        if any(m.ict_source_move_id or (m.state == 'done' and m.picking_id.is_intercompany_transfer) for m in self):
            raise UserError(_('Linked inter-company moves cannot be deleted.'))
