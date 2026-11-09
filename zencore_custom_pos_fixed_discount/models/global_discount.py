import math

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .discount_math import allocate_discount, refund_share


class PosOrder(models.Model):
    _inherit = 'pos.order'

    global_discount_type = fields.Selection([
        ('none', 'None'), ('percent', 'Percentage'), ('fixed', 'Fixed Amount'),
    ], default='none', required=True, copy=False)
    global_discount_input_value = fields.Float(string='Global Discount Input', default=0, copy=False)
    global_discount_amount = fields.Monetary(
        currency_field='currency_id', readonly=True, copy=False,
        help='Signed gross discount. Negative on returns; never a second posting line.')

    @api.model
    def _load_pos_data_fields(self, config):
        names = super()._load_pos_data_fields(config)
        # [] means "load ALL fields" in pos.load.mixin and load_data_params.
        # Turning it into a custom-only list drops lines/session/config from the
        # POS schema, causing order.setup -> _computeAllPrices -> undefined.map.
        if not names:
            return names
        return list(dict.fromkeys([*names,
            'global_discount_type', 'global_discount_input_value', 'global_discount_amount']))

    @api.model
    def _process_order(self, order, existing_order):
        # Older/offline clients can send False, bypassing the field's default.
        # Keep a saved discount when an incomplete update omits its type.
        if not order.get('global_discount_type'):
            discount_type = existing_order.global_discount_type if existing_order else 'none'
            order = dict(order, global_discount_type=discount_type or 'none')
        return super()._process_order(order, existing_order)

    @api.constrains('global_discount_type', 'global_discount_input_value')
    def _check_global_discount(self):
        for order in self:
            value = order.global_discount_input_value
            if not math.isfinite(value) or value < 0:
                raise ValidationError(_('Global discount must be a finite, non-negative number.'))
            if order.global_discount_type == 'percent' and value > 100:
                raise ValidationError(_('Global percentage discount cannot exceed 100%.'))
            if order.is_refund and order.global_discount_type != 'none' and value:
                raise ValidationError(_('Refund discounts are inherited from the original sale.'))

    def _ne_global_discount_plan(self):
        self.ensure_one()
        lines = self.lines.sorted(lambda line: (line.uuid or '', line.id))
        raw = lines.with_context(ne_skip_global_discount=True)._prepare_tax_base_line_values()
        Tax = self.env['account.tax']
        Tax._add_tax_details_in_base_lines(raw, self.company_id)
        Tax._round_base_lines_tax_details(raw, self.company_id)
        gross = [base['tax_details']['total_included_currency']
                 if line.qty > 0 and not line.refunded_orderline_id else 0
                 for line, base in zip(lines, raw)]
        allocated = allocate_discount(gross, self.global_discount_type,
                                      self.global_discount_input_value, self.currency_id.rounding)
        consumed = {}
        for index, line in enumerate(lines):
            source = line.refunded_orderline_id
            if source and line.qty < 0:
                previous = sum(abs(item.qty) for item in source.refund_orderline_ids
                               if item.order_id != self and item.order_id.state not in ('draft', 'cancel'))
                previous += consumed.get(source.id, 0)
                allocated[index] = -refund_share(source.global_discount_allocation,
                    source.qty, line.qty, previous, self.currency_id.round)
                consumed[source.id] = consumed.get(source.id, 0) + abs(line.qty)
        return dict(zip(lines.ids, allocated))

    def _compute_prices(self):
        for order in self:
            plan = order._ne_global_discount_plan()
            order.global_discount_amount = order.currency_id.round(sum(plan.values()))
            for line in order.lines:
                line.global_discount_allocation = plan.get(line.id, 0)
        result = super()._compute_prices()
        # The same canonical bases feed order totals, invoices and session closing.
        for order in self:
            bases = order.lines._prepare_tax_base_line_values()
            Tax = self.env['account.tax']
            Tax._add_tax_details_in_base_lines(bases, order.company_id)
            Tax._round_base_lines_tax_details(bases, order.company_id)
            for base in bases:
                detail = base['tax_details']
                sign = -1 if order.is_refund else 1
                base['record'].update({
                    'price_subtotal': sign * detail['total_excluded_currency'],
                    'price_subtotal_incl': sign * detail['total_included_currency'],
                })
        return result

    def _process_saved_order(self, draft):
        # Never trust amounts or hidden allocations received from an offline client.
        self._compute_prices()
        return super()._process_saved_order(draft)

    @api.onchange('global_discount_type', 'global_discount_input_value', 'lines')
    def _onchange_ne_global_discount(self):
        self._compute_prices()

    def _prepare_refund_values(self, current_session):
        return dict(super()._prepare_refund_values(current_session),
                    global_discount_type='none', global_discount_input_value=0,
                    global_discount_amount=0)

    def _prepare_invoice_vals(self):
        values = super()._prepare_invoice_vals()
        # Disclosure only: revenue/tax bases have already been reduced exactly once.
        notes = []
        for order in self:
            if not order.currency_id.is_zero(order.global_discount_amount):
                label = _('Global Discount Reversal') if order.is_refund else (
                    _('Global Discount (%s%%)', order.global_discount_input_value)
                    if order.global_discount_type == 'percent' else _('Global Discount (Fixed)'))
                notes.append((0, 0, {'display_type': 'line_note', 'name': '%s: %s %s' % (
                    label, order.currency_id.round(order.global_discount_amount), order.currency_id.name)}))
        values['invoice_line_ids'] += notes
        return values


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    global_discount_allocation = fields.Monetary(
        currency_field='currency_id', readonly=True, copy=False,
        help='Internal signed gross allocation for tax computation and partial returns.')

    @api.model
    def _load_pos_data_fields(self, config):
        names = super()._load_pos_data_fields(config)
        return list(dict.fromkeys([*names, 'global_discount_allocation'])) if names else names

    def _ne_price_for_gross(self, base, target):
        factor = 1 - base['discount'] / 100
        if not base['quantity'] or not factor:
            return base['price_unit']
        taxes = base['tax_ids']
        options = dict(rounding_method='round_globally', product=base['product_id'],
                       product_uom=base['product_uom_id'])
        details = taxes._get_tax_details(target / base['quantity'], base['quantity'],
                                        special_mode='total_included', **options)
        included = sum(data['tax_amount'] for data in details['taxes_data'] if data['tax'].price_include)
        price = (details['total_excluded'] + included) / (base['quantity'] * factor)
        check = taxes._get_tax_details(price * factor, base['quantity'], **options)
        if not math.isfinite(price) or abs(check['total_included'] - target) > 0.000001:
            raise ValidationError(_('The configured taxes cannot reconcile this discount. Check the tax configuration.'))
        return price

    def _prepare_base_line_for_taxes_computation(self):
        base = super()._prepare_base_line_for_taxes_computation()
        if self.env.context.get('ne_skip_global_discount') or not self.qty:
            return base
        plans = self.env.context.get('ne_global_discount_plans', {})
        plan = plans.get(self.order_id.id)
        if plan is None:
            plan = self.order_id._ne_global_discount_plan()
        allocation = plan.get(self.id, 0)
        if allocation:
            Tax = self.env['account.tax']
            Tax._add_tax_details_in_base_line(base, self.order_id.company_id)
            gross = base['tax_details']['raw_total_included_currency']
            sign = -1 if self.order_id.is_refund else 1
            base['price_unit'] = self._ne_price_for_gross(base, gross - allocation * sign)
            base.pop('tax_details', None)
        return base

    def _prepare_tax_base_line_values(self):
        if self.env.context.get('ne_skip_global_discount') or 'ne_global_discount_plans' in self.env.context:
            return super()._prepare_tax_base_line_values()
        # Compute once per order, rather than once per line, during accounting/invoicing.
        plans = {order.id: order._ne_global_discount_plan() for order in self.order_id}
        return super(PosOrderLine, self.with_context(ne_global_discount_plans=plans))._prepare_tax_base_line_values()

    def _compute_amount_line_all(self):
        self.ensure_one()
        base = self._prepare_base_line_for_taxes_computation()
        Tax = self.env['account.tax']
        Tax._add_tax_details_in_base_lines([base], self.order_id.company_id)
        Tax._round_base_lines_tax_details([base], self.order_id.company_id)
        sign = -1 if self.order_id.is_refund else 1
        return {'price_subtotal': sign * base['tax_details']['total_excluded_currency'],
                'price_subtotal_incl': sign * base['tax_details']['total_included_currency']}

    @api.onchange('qty', 'discount', 'fixed_discount_amount', 'price_unit', 'tax_ids')
    def _onchange_qty(self):
        for line in self.filtered('product_id'):
            line.update(line._compute_amount_line_all())

    def _prepare_refund_data(self, refund_order, PosPackOperationLot):
        values = super()._prepare_refund_data(refund_order, PosPackOperationLot)
        qty = values.get('qty', -self.qty)
        values['fixed_discount_amount'] = self._get_fixed_discount_for_quantity(qty)
        values['global_discount_allocation'] = -refund_share(self.global_discount_allocation,
            self.qty, qty, self.refunded_qty, self.currency_id.round)
        return values
