import hashlib
import json
import math
import uuid
import pytz

from odoo import api, fields, models, _, Command
from odoo.exceptions import AccessError, UserError
from odoo.tools.float_utils import float_compare, float_is_zero


class PosMarkout(models.Model):
    _name = 'pos.markout'
    _description = 'POS Marked Out Transaction'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True, copy=False, readonly=True, default='/')
    uuid = fields.Char(required=True, copy=False, readonly=True, index=True)
    payload_hash = fields.Char(required=True, copy=False, readonly=True, groups='base.group_system')
    state = fields.Selection([('confirmed', 'Confirmed')], required=True, readonly=True, default='confirmed', index=True)
    date = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now, index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    config_id = fields.Many2one('pos.config', required=True, readonly=True, index=True, check_company=True)
    session_id = fields.Many2one('pos.session', required=True, readonly=True, index=True, check_company=True)
    category_id = fields.Many2one('pos.markout.category', required=True, readonly=True, index=True, ondelete='restrict', check_company=True)
    parent_category_id = fields.Many2one(related='category_id.parent_id', store=True, readonly=True, index=True)
    employee_id = fields.Many2one('hr.employee', required=True, readonly=True, index=True, ondelete='restrict', check_company=True, groups='hr.group_hr_user')
    employee_name = fields.Char(required=True, readonly=True, index=True)
    employee_badge = fields.Char(readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', required=True, readonly=True, index=True, ondelete='restrict', check_company=True)
    partner_name = fields.Char(required=True, readonly=True, index=True)
    cashier_id = fields.Many2one('res.users', required=True, readonly=True, index=True)
    line_ids = fields.One2many('pos.markout.line', 'markout_id', readonly=True)
    stock_move_ids = fields.Many2many('stock.move', 'pos_markout_stock_move_rel', 'markout_id', 'move_id', readonly=True, groups='stock.group_stock_user')
    retail_reference_total = fields.Monetary(compute='_compute_reference_total', store=True, readonly=True, currency_field='currency_id')
    charged_amount = fields.Monetary(readonly=True, default=0.0, currency_field='currency_id')
    line_count = fields.Integer(compute='_compute_reference_total', store=True)
    note = fields.Char(readonly=True)

    _unique_uuid = models.Constraint('unique(uuid)', 'This Marked Out request has already been recorded.')

    @api.depends('line_ids.reference_total')
    def _compute_reference_total(self):
        for markout in self:
            markout.retail_reference_total = sum(markout.line_ids.mapped('reference_total'))
            markout.line_count = len(markout.line_ids)

    @api.model
    def _check_pos_session(self, session_id, config_id):
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (session_id, config_id)):
            raise AccessError(_('Invalid POS session.'))
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened' or session.config_id.id != config_id:
            raise UserError(_('Marked Out requires the matching currently open POS session.'))
        config = session.config_id
        company = config.company_id
        if company not in self.env.companies:
            raise AccessError(_('This POS is outside your allowed companies.'))
        return session, config, company

    @api.model
    def _check_view_permission(self):
        user = self.env.user
        if not (user.pos_markout_can_view or user.pos_markout_can_view_reports or user.has_group('base.group_system')):
            raise AccessError(_('You do not have permission to view Marked Out records.'))

    @api.model
    def _check_create_permission(self):
        user = self.env.user
        if not (user.pos_markout_can_create and user.pos_markout_allowed_category_ids):
            raise AccessError(_('You do not have permission to create Marked Out records. Ask an administrator to grant access.'))

    @api.model
    def _allowed_child_categories(self, company):
        allowed_ids = self.env.user.pos_markout_allowed_category_ids.ids
        return self.env['pos.markout.category'].sudo().search([
            ('id', 'in', allowed_ids), ('active', '=', True), ('parent_id', '!=', False),
            ('parent_id.active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
            '|', ('parent_id.company_id', '=', False), ('parent_id.company_id', '=', company.id),
        ])

    @api.model
    def get_pos_setup(self, session_id, config_id):
        session, config, company = self._check_pos_session(session_id, config_id)
        self._check_create_permission()
        categories = self._allowed_child_categories(company)
        children_by_parent = {}
        for category in categories:
            children_by_parent.setdefault(category.parent_id.id, []).append({
                'id': category.id, 'name': category.name, 'code': category.code,
                'product_ids': category.product_ids.ids,
            })
        parents = categories.mapped('parent_id').sorted(lambda parent: (parent.sequence, parent.id))
        return {
            'session_id': session.id,
            'config_id': config.id,
            'categories': [{
                'id': parent.id, 'name': parent.name, 'code': parent.code, 'icon': parent.icon,
                'children': children_by_parent[parent.id],
            } for parent in parents],
        }

    @api.model
    def _check_child_access(self, company, category_id):
        if category_id is None or category_id is False:
            raise UserError(_('Please select a subcategory first.'))
        if isinstance(category_id, bool) or not isinstance(category_id, int) or category_id <= 0:
            raise AccessError(_('Invalid Marked Out category.'))
        category = self.env['pos.markout.category'].sudo().browse(category_id).exists()
        allowed = self._allowed_child_categories(company)
        if not category or category not in allowed:
            raise AccessError(_('You are not allowed to use this Marked Out category.'))
        return category

    @api.model
    def search_pos_employees(self, session_id, config_id, category_id=None, query=''):
        _session, _config, company = self._check_pos_session(session_id, config_id)
        self._check_create_permission()
        if category_id is not None:
            self._check_child_access(company, category_id)
        elif not self._allowed_child_categories(company):
            raise AccessError(_('You have no permitted active subcategories for this POS company.'))
        if not isinstance(query, str) or len(query) > 100:
            raise UserError(_('Enter a shorter employee name or badge ID.'))
        query = query.strip()
        Employee = self.env['hr.employee'].sudo().with_company(company)
        base_domain = [('active', '=', True), ('company_id', '=', company.id)]
        # Search the exact badge separately so it is never pushed out by a large
        # set of partial name matches. Use the native Badge ID as a string so
        # leading zeroes survive a scanner or manual lookup. Never expose PINs.
        badge_match = Employee.search(base_domain + [('barcode', '=', query)], limit=1) if query else Employee.browse()
        name_domain = [('name', 'ilike', query)] if query else []
        name_matches = Employee.search(base_domain + name_domain, limit=30, order='name, id')
        employees = (badge_match | (name_matches - badge_match))[:30]
        results = []
        for employee in employees:
            partner = employee.work_contact_id
            contact_available = bool(partner and partner.active and (not partner.company_id or partner.company_id == company))
            # Return only the identification/contact projection needed by the
            # cashier, never the employee's private HR or authentication data.
            results.append({
                'id': employee.id,
                'name': employee.name,
                'badge': employee.barcode or '',
                'partner_id': partner.id if contact_available else False,
                'partner_name': partner.display_name if contact_available else '',
                'department': employee.department_id.name or '',
                'work_location': employee.work_location_id.name or '',
                'company': employee.company_id.name,
            })
        return results

    @api.model
    def _normalize_uuid(self, value):
        if not isinstance(value, str) or len(value) > 64:
            raise UserError(_('Invalid Marked Out request reference.'))
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError, TypeError):
            raise UserError(_('Invalid Marked Out request reference.')) from None

    @api.model
    def _normalize_lines(self, raw_lines, company, category):
        if not isinstance(raw_lines, list) or not raw_lines or len(raw_lines) > 200:
            raise UserError(_('Add at least one product; up to 200 distinct products are allowed.'))
        merged = {}
        for item in raw_lines:
            if not isinstance(item, dict):
                raise UserError(_('Invalid Marked Out product line.'))
            if item.get('is_combo'):
                raise UserError(_('POS combo products require a component-aware stock workflow and are not supported.'))
            product_id, quantity = item.get('product_id'), item.get('qty')
            if isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0:
                raise UserError(_('Invalid product in Marked Out cart.'))
            if isinstance(quantity, bool) or not isinstance(quantity, (float, int)) or not math.isfinite(quantity) or quantity <= 0:
                raise UserError(_('Product quantity must be a positive number.'))
            note = item.get('note', '')
            if not isinstance(note, str) or len(note) > 500:
                raise UserError(_('Product notes must be plain text under 500 characters.'))
            merged.setdefault(product_id, {'qty': 0.0, 'note': note.strip()})
            merged[product_id]['qty'] += float(quantity)
        products = self.env['product.product'].sudo().with_company(company).browse(list(merged)).exists()
        if len(products) != len(merged):
            raise UserError(_('A selected product is no longer available. Refresh the POS and try again.'))
        if category.product_ids and any(product not in category.product_ids for product in products):
            raise UserError(_('This category does not allow one or more selected products.'))
        normalized = []
        for product in products:
            qty = merged[product.id]['qty']
            if not math.isfinite(qty):
                raise UserError(_('The total quantity for a product is too large.'))
            if (not product.active or not product.sale_ok or not product.available_in_pos
                    or (product.company_id and product.company_id != company)):
                raise UserError(_('%(product)s is not available in this POS.', product=product.display_name))
            if getattr(product, 'type', '') == 'combo':
                raise UserError(_('POS combo products require a component-aware stock workflow and are not supported.'))
            rounding = product.uom_id.rounding
            if float_is_zero(qty, precision_rounding=rounding) or float_compare(qty, 0, precision_rounding=rounding) <= 0:
                raise UserError(_('Product quantity is below the unit precision.'))
            if getattr(product, 'tracking', 'none') != 'none':
                raise UserError(_('Lot- or serial-tracked products need a stock-tracking workflow and are not supported here.'))
            normalized.append({
                'product': product,
                'qty': qty,
                'note': merged[product.id]['note'],
                'list_price': product.lst_price,
                'cost': product.standard_price,
            })
        return normalized

    @api.model
    def _business_date(self, rule):
        local_zone = pytz.timezone(rule.timezone)
        now = fields.Datetime.now()
        utc_now = pytz.UTC.localize(now) if now.tzinfo is None else now.astimezone(pytz.UTC)
        return utc_now.astimezone(local_zone).date()

    @api.model
    def _check_and_reserve_benefits(self, employee, category, company, config, lines):
        rules = self.env['pos.benefit.rule'].sudo().search([
            ('active', '=', True), ('category_id', '=', category.id),
            '|', ('company_id', '=', company.id), ('company_id', '=', False),
        ])
        staff_category = self.env.ref('pos_employee_benefits_markout.category_staff_food_drink', raise_if_not_found=False)
        if category == staff_category and not rules.filtered('product_ids'):
            raise UserError(_('Daily Latte products are not configured yet. Ask an administrator to select the eligible Latte variants.'))
        # Serialize all benefit claims for one employee before reading today's usage.
        self.env.cr.execute('SELECT id FROM hr_employee WHERE id = %s FOR UPDATE', (employee.id,))
        reservations = []
        Usage = self.env['pos.markout.benefit.usage'].sudo()
        for rule in rules:
            rule_lines = [line for line in lines if line['product'] in rule.product_ids]
            if not rule_lines:
                continue
            qty = sum(line['qty'] for line in rule_lines)
            benefit_date = self._business_date(rule)
            domain = [
                ('employee_id', '=', employee.id), ('rule_id', '=', rule.id),
                ('company_id', '=', company.id), ('benefit_date', '=', benefit_date),
            ]
            if rule.quota_scope == 'pos':
                domain.append(('config_id', '=', config.id))
            used_qty = sum(Usage.search(domain).mapped('quantity'))
            if float_compare(used_qty + qty, rule.max_qty, precision_rounding=rule.product_ids[0].uom_id.rounding) > 0:
                raise UserError(_('Daily Latte benefit already used (%(used)s/%(limit)s) today.',
                                  used=used_qty, limit=rule.max_qty))
            reservations.append({
                'rule_id': rule.id, 'employee_id': employee.id, 'company_id': company.id,
                'config_id': config.id, 'benefit_date': benefit_date, 'quantity': qty,
                'benefit_name': rule.name, 'employee_name': employee.name,
                'employee_badge': employee.barcode or '',
                'max_quantity': rule.max_qty, 'quota_scope': rule.quota_scope,
            })
        return reservations

    @api.model
    def _post_stock_moves(self, markout, category, config, company):
        if category.stock_policy == 'unconfigured':
            raise UserError(_('Stock handling is not configured for this category. Ask an administrator to choose its approved disposition.'))
        if category.stock_policy == 'none':
            return self.env['stock.move']
        source_stock = config.picking_type_id.default_location_src_id
        if not source_stock or source_stock.usage != 'internal':
            raise UserError(_('This POS has no valid internal stock source location.'))
        created_moves = self.env['stock.move']
        Move = self.env['stock.move'].sudo().with_company(company)
        for line in markout.line_ids:
            product = line.product_id
            if not getattr(product, 'is_storable', product.type == 'product'):
                continue
            operational_location = category.stock_location_id
            if category.stock_policy == 'prepare' and not operational_location:
                operational_location = product.with_company(company).property_stock_inventory
            if not operational_location:
                raise UserError(_('Configure an inventory loss destination for %(product)s.', product=product.display_name))
            if operational_location.company_id and operational_location.company_id != company:
                raise AccessError(_('The stock destination belongs to another company.'))
            if category.stock_policy in ('prepare', 'consume'):
                if operational_location.usage != 'inventory':
                    raise UserError(_('Prepared products and write-offs require an Inventory usage destination.'))
                source, destination = source_stock, operational_location
            elif category.stock_policy == 'restock':
                source, destination = operational_location, source_stock
            else:
                raise UserError(_('Select a supported inventory flow for this category.'))
            if source == destination:
                raise UserError(_('The POS stock source and category stock location must be different.'))
            values = {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'product_uom': product.uom_id.id,
                'location_id': source.id,
                'location_dest_id': destination.id,
                'company_id': company.id,
                'origin': markout.name,
                'reference': markout.name,
                'price_unit': line.cost_unit,
            }
            move = Move.create(values)
            move._action_confirm()
            if source.usage == 'internal':
                move._action_assign()
                if float_compare(move.quantity, line.quantity, precision_rounding=product.uom_id.rounding) < 0:
                    raise UserError(_('Not enough stock for %(product)s at %(location)s.',
                                      product=product.display_name, location=source.display_name))
            # These standalone moves have no picking/scrap document for Odoo's
            # computed reference. Supply the Marked Out reference explicitly
            # before native valuation builds the journal labels and entry ref.
            move.write({
                'quantity': line.quantity, 'picked': True,
                'reference': markout.name,
            })
            move._action_done()
            if move.state != 'done':
                raise UserError(_('The stock movement for %(product)s did not complete.', product=product.display_name))
            line.stock_move_ids = [Command.link(move.id)]
            created_moves |= move
        return created_moves

    @api.model
    def submit_markout(self, session_id, config_id, category_id, employee_id, request_uuid, raw_lines, note=''):
        session, config, company = self._check_pos_session(session_id, config_id)
        self._check_create_permission()
        category = self._check_child_access(company, category_id)
        if not isinstance(employee_id, int) or isinstance(employee_id, bool) or employee_id <= 0:
            raise UserError(_('Select an employee from the search results.'))
        request_uuid = self._normalize_uuid(request_uuid)
        if not isinstance(note, str) or len(note) > 500:
            raise UserError(_('Transaction notes must be plain text under 500 characters.'))
        # Serialize retries so a response lost by the browser cannot duplicate
        # the mark-out or its stock movement.
        self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (request_uuid,))
        employee = self.env['hr.employee'].sudo().with_company(company).browse(employee_id).exists()
        if not employee or not employee.active or employee.company_id != company:
            raise UserError(_('Select an active employee from this POS company.'))
        lines = self._normalize_lines(raw_lines, company, category)
        payload = {
            'session_id': session.id, 'config_id': config.id, 'category_id': category.id,
            'employee_id': employee.id,
            'lines': [{'product_id': line['product'].id, 'qty': line['qty'], 'note': line['note']} for line in lines],
            'note': note.strip(),
        }
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        existing = self.sudo().search([('uuid', '=', request_uuid)], limit=1)
        if existing:
            if existing.cashier_id.id != self.env.uid:
                raise AccessError(_('This Marked Out request belongs to another user.'))
            if existing.payload_hash != payload_hash:
                raise UserError(_('This request reference was already used with different cart contents. Refresh before retrying.'))
            return self._response(existing)

        # Resolve the standard HR work contact again on the server instead of
        # trusting a contact ID cached or supplied by the POS client.
        partner = employee.work_contact_id
        if not partner or not partner.active:
            raise UserError(_('This employee has no active Work Contact. Update the employee record in Employees.'))
        if partner.company_id and partner.company_id != company:
            raise AccessError(_('The employee Work Contact belongs to another company.'))
        reservations = self._check_and_reserve_benefits(employee, category, company, config, lines)
        reference = self.env['ir.sequence'].with_company(company).next_by_code('pos.markout') or '/'
        markout = self.sudo().create({
            'name': reference, 'uuid': request_uuid, 'payload_hash': payload_hash,
            'company_id': company.id, 'config_id': config.id, 'session_id': session.id,
            'category_id': category.id, 'employee_id': employee.id, 'partner_id': partner.id,
            'employee_name': employee.name, 'employee_badge': employee.barcode or '',
            'partner_name': partner.display_name,
            'cashier_id': self.env.uid, 'date': fields.Datetime.now(), 'note': note.strip(),
            'line_ids': [Command.create({
                'product_id': line['product'].id,
                'description': line['product'].display_name,
                'quantity': line['qty'],
                'list_price_snapshot': line['list_price'],
                'cost_unit': line['cost'],
                'note': line['note'],
            }) for line in lines],
        })
        stock_moves = self._post_stock_moves(markout, category, config, company)
        markout.stock_move_ids = [Command.set(stock_moves.ids)]
        Usage = self.env['pos.markout.benefit.usage'].sudo()
        for reservation in reservations:
            Usage.create({**reservation, 'markout_id': markout.id})
        markout.message_post(body=_(
            'Marked Out %(reference)s confirmed by %(cashier)s for %(employee)s. Category: %(category)s.',
            reference=markout.name, cashier=self.env.user.display_name,
            employee=employee.name, category=category.display_name))
        return self._response(markout)

    @api.model
    def _response(self, markout):
        return {
            'id': markout.id, 'reference': markout.name, 'state': markout.state,
            'employee': markout.employee_name, 'partner': markout.partner_name,
            'category': markout.category_id.display_name,
            'retail_reference_total': markout.retail_reference_total,
            'charged_amount': markout.charged_amount,
            'currency_id': markout.company_id.currency_id.id,
            'date': fields.Datetime.to_string(markout.date),
            'lines': [{'name': line.description, 'quantity': line.quantity,
                       'reference_total': line.reference_total} for line in markout.line_ids],
        }

    @api.model
    def get_markout_status(self, session_id, config_id, request_uuid):
        request_uuid = self._normalize_uuid(request_uuid)
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (session_id, config_id)):
            raise AccessError(_('Invalid POS session.'))
        # Coordinate recovery with any submission using this same request UUID.
        self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (request_uuid,))
        markout = self.sudo().search([('uuid', '=', request_uuid)], limit=1)
        if not markout:
            return {'state': 'not_found'}
        if (markout.cashier_id.id != self.env.uid or markout.session_id.id != session_id
                or markout.config_id.id != config_id or markout.company_id not in self.env.companies):
            raise AccessError(_('This Marked Out request belongs to another cashier, session, or company.'))
        return self._response(markout)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Marked Out records can only be created through the validated POS workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise AccessError(_('Confirmed Marked Out records are immutable.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Confirmed Marked Out records cannot be deleted.'))


class PosMarkoutLine(models.Model):
    _name = 'pos.markout.line'
    _description = 'POS Marked Out Item'
    _order = 'id'
    _check_company_auto = True

    markout_id = fields.Many2one('pos.markout', required=True, index=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='markout_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='markout_id.currency_id')
    date = fields.Datetime(related='markout_id.date', store=True, index=True)
    category_id = fields.Many2one(related='markout_id.category_id', store=True, index=True)
    employee_id = fields.Many2one(related='markout_id.employee_id', store=True, index=True, groups='hr.group_hr_user')
    employee_name = fields.Char(related='markout_id.employee_name', store=True, index=True)
    employee_badge = fields.Char(related='markout_id.employee_badge', store=True, index=True)
    partner_name = fields.Char(related='markout_id.partner_name', store=True, index=True)
    config_id = fields.Many2one(related='markout_id.config_id', store=True, index=True)
    product_id = fields.Many2one('product.product', required=True, readonly=True, ondelete='restrict', check_company=True)
    description = fields.Char(required=True, readonly=True)
    quantity = fields.Float(required=True, readonly=True, digits='Product Unit')
    list_price_snapshot = fields.Float(readonly=True, digits='Product Price')
    cost_unit = fields.Float(readonly=True, digits='Product Price', groups='point_of_sale.group_pos_manager')
    reference_total = fields.Monetary(compute='_compute_reference_total', store=True, readonly=True, currency_field='currency_id')
    stock_cost_total = fields.Monetary(compute='_compute_reference_total', store=True, readonly=True, currency_field='currency_id', groups='point_of_sale.group_pos_manager')
    note = fields.Char(readonly=True)
    stock_move_ids = fields.Many2many('stock.move', 'pos_markout_line_stock_move_rel', 'line_id', 'move_id', readonly=True, groups='stock.group_stock_user')

    @api.depends('quantity', 'list_price_snapshot', 'cost_unit')
    def _compute_reference_total(self):
        for line in self:
            line.reference_total = line.quantity * line.list_price_snapshot
            line.stock_cost_total = line.quantity * line.cost_unit

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Marked Out lines can only be created by the validated POS workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise AccessError(_('Confirmed Marked Out items are immutable.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Confirmed Marked Out items cannot be deleted.'))


class PosMarkoutBenefitUsage(models.Model):
    _name = 'pos.markout.benefit.usage'
    _description = 'POS Marked Out Daily Benefit Usage'
    _order = 'benefit_date desc, id desc'
    _check_company_auto = True

    markout_id = fields.Many2one('pos.markout', required=True, index=True, ondelete='restrict', check_company=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True, ondelete='restrict', check_company=True, groups='hr.group_hr_user')
    rule_id = fields.Many2one('pos.benefit.rule', required=True, index=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    config_id = fields.Many2one('pos.config', required=True, index=True, check_company=True)
    benefit_date = fields.Date(required=True, index=True)
    quantity = fields.Float(required=True, digits='Product Unit')
    benefit_name = fields.Char(required=True, readonly=True)
    employee_name = fields.Char(required=True, readonly=True)
    employee_badge = fields.Char(readonly=True)
    max_quantity = fields.Float(required=True, readonly=True, digits='Product Unit')
    quota_scope = fields.Selection([
        ('company', 'Across Company POS Registers'),
        ('pos', 'Per POS Register'),
    ], required=True, readonly=True)
    used_quantity = fields.Float(compute='_compute_daily_totals', digits='Product Unit')
    remaining_quantity = fields.Float(compute='_compute_daily_totals', digits='Product Unit')

    _unique_markout_rule = models.Constraint('unique(markout_id, rule_id)', 'A benefit allowance can only be consumed once per Marked Out transaction.')

    @api.depends('employee_id', 'rule_id', 'company_id', 'config_id', 'benefit_date', 'quantity', 'quota_scope', 'max_quantity')
    def _compute_daily_totals(self):
        Usage = self.env['pos.markout.benefit.usage'].sudo()
        for usage in self.sudo():
            domain = [
                ('employee_id', '=', usage.employee_id.id),
                ('rule_id', '=', usage.rule_id.id),
                ('company_id', '=', usage.company_id.id),
                ('benefit_date', '=', usage.benefit_date),
            ]
            if usage.quota_scope == 'pos':
                domain.append(('config_id', '=', usage.config_id.id))
            used = sum(Usage.search(domain).mapped('quantity'))
            usage.used_quantity = used
            usage.remaining_quantity = max(0.0, usage.max_quantity - used)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Benefit usage can only be recorded by the validated POS workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Benefit usage records are immutable.'))

    def unlink(self):
        raise AccessError(_('Benefit usage records cannot be deleted.'))
