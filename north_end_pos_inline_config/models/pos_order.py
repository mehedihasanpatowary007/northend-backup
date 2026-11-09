from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    # UUID links survive unsaved/offline orders without depending on database IDs
    # or the order in which the parent and children reach the server.
    ne_parent_uuid = fields.Char(string='Add-on parent UUID', index=True, copy=False)
    ne_parent_label = fields.Char(string='Add-on for', copy=False)

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['ne_parent_uuid', 'ne_parent_label']

    def _prepare_refund_data(self, refund_order, PosPackOperationLot):
        values = super()._prepare_refund_data(refund_order, PosPackOperationLot)
        values.update(ne_parent_uuid=False, ne_parent_label=self.ne_parent_label)
        return values


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _process_saved_order(self, draft):
        for order in self:
            order._ne_validate_addons()
        return super()._process_saved_order(draft)

    def _ne_validate_addons(self):
        self.ensure_one()
        by_uuid = {line.uuid: line for line in self.lines}
        for line in self.lines.filtered('ne_parent_uuid'):
            parent = by_uuid.get(line.ne_parent_uuid)
            if not parent or parent == line or parent.ne_parent_uuid:
                raise ValidationError(_('An add-on must belong to a coffee line in the same order.'))
            if bool(line.qty < 0) != bool(parent.qty < 0):
                raise ValidationError(_('Coffee and its add-ons must have the same sale/refund direction.'))
            if line.refunded_orderline_id:
                original_parent = line.refunded_orderline_id.ne_parent_uuid
                if original_parent != parent.refunded_orderline_id.uuid:
                    raise ValidationError(_('The refunded add-on does not belong to this coffee.'))
                continue
            if line.product_id.product_tmpl_id not in parent.product_id.pos_optional_product_ids:
                raise ValidationError(_('%s is not an allowed add-on for this product.', line.product_id.display_name))
            # Optional-product links are explicitly loaded for this POS, even
            # when the add-on itself is hidden from the main product grid.
            if not line.product_id.sale_ok:
                raise ValidationError(_('%s must be a sellable product.', line.product_id.display_name))
            if parent.qty <= 0 or parent.price_unit < 0 or line.qty <= 0 or line.price_unit < 0:
                raise ValidationError(_('Add-on quantities must be positive and prices cannot be negative.'))
            limit = self.config_id.ne_addon_limit
            total = sum(self.lines.filtered(
                lambda item: item.ne_parent_uuid == parent.uuid and item.product_id == line.product_id
            ).mapped('qty'))
            if limit and total > limit:
                raise ValidationError(_('The maximum quantity for this add-on is %s.', limit))

    def _refund(self):
        orders = super()._refund()
        for order in orders:
            original_to_refund = {line.refunded_orderline_id.uuid: line for line in order.lines}
            for line in order.lines:
                original = line.refunded_orderline_id
                if not original:
                    continue
                parent = original_to_refund.get(original.ne_parent_uuid)
                line.ne_parent_uuid = parent.uuid if parent else False
                line.ne_parent_label = original.ne_parent_label
                if 'fixed_discount_amount' in line._fields and original.qty:
                    line.fixed_discount_amount = original.fixed_discount_amount * abs(line.qty / original.qty)
                    line._onchange_amount_line_all()
            order._compute_prices()
        return orders
