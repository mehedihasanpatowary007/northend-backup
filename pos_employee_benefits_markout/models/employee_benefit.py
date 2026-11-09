from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class PosMarkoutEmployeeBenefit(models.Model):
    _inherit = 'pos.markout'

    @api.model
    def _benefit_rules_for_category(self, category, company):
        return self.env['pos.benefit.rule'].sudo().search([
            ('active', '=', True), ('category_id', '=', category.id),
            '|', ('company_id', '=', company.id), ('company_id', '=', False),
        ])

    @api.model
    def _is_staff_benefit_category(self, category):
        staff_parent = self.env.ref('pos_employee_benefits_markout.category_staff', raise_if_not_found=False)
        staff_category = self.env.ref('pos_employee_benefits_markout.category_staff_food_drink', raise_if_not_found=False)
        return bool(category == staff_category or (staff_parent and category.parent_id == staff_parent))

    @api.model
    def search_pos_employees(self, session_id, config_id, category_id=None, query=''):
        employees = super().search_pos_employees(session_id, config_id, category_id=category_id, query=query)
        if category_id is None:
            return employees
        _session, _config, company = self._check_pos_session(session_id, config_id)
        category = self._check_child_access(company, category_id)
        rules = self._benefit_rules_for_category(category, company)
        restricted = bool(rules) or self._is_staff_benefit_category(category)
        for employee in employees:
            applicable = rules.filtered(
                lambda rule: not rule.employee_id or rule.employee_id.id == employee['id']
            )
            products = applicable.mapped('product_ids')
            if category.product_ids:
                products &= category.product_ids
            employee['benefit_restricted'] = restricted
            employee['benefit_product_ids'] = products.ids if restricted else []
        return employees

    @api.model
    def _benefit_day_bounds(self, rule, benefit_date):
        """Return the UTC boundaries of one local business day, including DST."""
        zone = pytz.timezone(rule.timezone)
        day = fields.Date.to_date(benefit_date)
        start = zone.localize(datetime.combine(day, time.min), is_dst=False)
        end = zone.localize(datetime.combine(day + timedelta(days=1), time.min), is_dst=False)
        return (
            start.astimezone(pytz.UTC).replace(tzinfo=None),
            end.astimezone(pytz.UTC).replace(tzinfo=None),
        )

    @api.model
    def _benefit_used_quantity(self, employee, rule, company, config, benefit_date, quota_scope=None):
        # Count confirmed product consumption rather than rule IDs. Assigning
        # an override after breakfast must not reset that employee's daily use.
        start, end = self._benefit_day_bounds(rule, benefit_date)
        products = rule.product_ids
        if not rule.employee_id:
            # Employee overrides replace matching default products, rather
            # than drawing down both the personal and shared product pools.
            overrides = self._benefit_rules_for_category(rule.category_id, company).filtered(
                lambda candidate: candidate.employee_id == employee
            )
            products -= overrides.mapped('product_ids')
        if not products:
            return 0.0
        domain = [
            ('markout_id.employee_id', '=', employee.id),
            ('markout_id.category_id', '=', rule.category_id.id),
            ('markout_id.company_id', '=', company.id),
            ('markout_id.state', '=', 'confirmed'),
            ('markout_id.date', '>=', start), ('markout_id.date', '<', end),
            ('product_id', 'in', products.ids),
        ]
        if (quota_scope or rule.quota_scope) == 'pos':
            domain.append(('markout_id.config_id', '=', config.id))
        return sum(self.env['pos.markout.line'].sudo().search(domain).mapped('quantity'))

    @api.model
    def _check_and_reserve_benefits(self, employee, category, company, config, lines):
        # A real row update makes simultaneous Repeatable Read transactions
        # conflict and retry, instead of retaining an older usage snapshot after
        # waiting on a read-only FOR UPDATE lock.
        self.env.cr.execute(
            'UPDATE hr_employee SET write_date = write_date WHERE id = %s', [employee.id],
        )
        employee.invalidate_recordset(['active', 'company_id', 'name', 'barcode'])
        if not employee.active or employee.company_id != company:
            raise UserError(_('Select an active employee from this POS company.'))
        rules = self._benefit_rules_for_category(category, company)
        if not rules and not self._is_staff_benefit_category(category):
            return []

        employee_rules = rules.filtered(lambda rule: rule.employee_id == employee)
        defaults = rules.filtered(lambda rule: not rule.employee_id)
        quantities = {}
        selected_rules = {}
        for line in lines:
            product = line['product']
            matched = employee_rules.filtered(lambda rule: product in rule.product_ids)
            if not matched:
                matched = defaults.filtered(lambda rule: product in rule.product_ids)
            if not matched:
                raise UserError(_(
                    '%(product)s is not allowed for %(employee)s.',
                    employee=employee.name, product=product.display_name,
                ))
            if len(matched) != 1:
                raise UserError(_('Benefit rules overlap. Ask a manager to keep one applicable rule per employee and product.'))
            rule = matched[0]
            selected_rules[rule.id] = rule
            quantities[rule.id] = quantities.get(rule.id, 0.0) + line['qty']

        reservations = []
        for rule_id, rule in selected_rules.items():
            quantity = quantities[rule_id]
            benefit_date = self._business_date(rule)
            used = self._benefit_used_quantity(employee, rule, company, config, benefit_date)
            if float_compare(used + quantity, rule.max_qty, precision_rounding=rule.product_ids[0].uom_id.rounding) > 0:
                raise UserError(_(
                    '%(employee)s has only %(remaining)s left today for %(benefit)s.',
                    employee=employee.name, remaining=max(0.0, rule.max_qty - used),
                    benefit=rule.name,
                ))
            reservations.append({
                'rule_id': rule.id, 'employee_id': employee.id, 'company_id': company.id,
                'config_id': config.id, 'benefit_date': benefit_date, 'quantity': quantity,
                'benefit_name': rule.name, 'employee_name': employee.name,
                'employee_badge': employee.barcode or '',
                'max_quantity': rule.max_qty, 'quota_scope': rule.quota_scope,
            })
        return reservations


class PosMarkoutEmployeeBenefitUsage(models.Model):
    _inherit = 'pos.markout.benefit.usage'

    @api.depends(
        'employee_id', 'rule_id', 'rule_id.product_ids', 'rule_id.category_id',
        'rule_id.timezone', 'company_id', 'config_id', 'benefit_date',
        'quantity', 'quota_scope', 'max_quantity',
    )
    def _compute_daily_totals(self):
        Markout = self.env['pos.markout'].sudo()
        for usage in self.sudo():
            used = Markout._benefit_used_quantity(
                usage.employee_id, usage.rule_id, usage.company_id,
                usage.config_id, usage.benefit_date, quota_scope=usage.quota_scope,
            )
            usage.used_quantity = used
            usage.remaining_quantity = max(0.0, usage.max_quantity - used)
