import math
import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class PosBenefitRule(models.Model):
    _name = 'pos.benefit.rule'
    _description = 'POS Employee Benefit Rule'
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=False)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one('res.company', index=True, ondelete='cascade', default=lambda self: self.env.company)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', index=True, ondelete='restrict', check_company=True,
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        help='Leave empty for a default allowance for all employees. An employee-specific allowance overrides the default for its selected products.')
    category_id = fields.Many2one(
        'pos.markout.category', required=True, index=True, ondelete='restrict', check_company=True,
        domain="[('parent_id', '!=', False)]")
    product_ids = fields.Many2many(
        'product.product', 'pos_benefit_rule_product_rel', 'rule_id', 'product_id',
        string='Eligible Products', required=True)
    max_qty = fields.Float(
        string='Daily Quantity', required=True, default=1.0, digits='Product Unit',
        help='One shared daily allowance for the selected products. Use separate rules when products have independent quantities.')
    period = fields.Selection([('daily', 'Per Business Day')], required=True, default='daily')
    quota_scope = fields.Selection([
        ('company', 'Across All POS Registers in the Company'),
        ('pos', 'Per POS Register'),
    ], required=True, default='company')
    timezone = fields.Char(required=True, default=lambda self: self.env.company.partner_id.tz or 'UTC')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.company_id = self.employee_id.company_id

    @api.constrains('category_id', 'company_id', 'employee_id', 'product_ids')
    def _check_category_company(self):
        for rule in self.sudo():
            if not rule.category_id.parent_id:
                raise ValidationError(_('Choose a Marked Out subcategory for the benefit allowance.'))
            if (rule.company_id and rule.category_id.company_id
                    and rule.company_id != rule.category_id.company_id):
                raise ValidationError(_('The benefit rule and category must belong to the same company.'))
            if rule.employee_id and rule.company_id != rule.employee_id.company_id:
                raise ValidationError(_('An employee-specific benefit rule must use that employee\'s company.'))
            if rule.company_id and any(
                    product.company_id and product.company_id != rule.company_id
                    for product in rule.product_ids):
                raise ValidationError(_('Benefit products must be shared or belong to the rule company.'))

    @api.constrains('active', 'category_id', 'company_id', 'employee_id', 'product_ids')
    def _check_overlapping_products(self):
        Rule = self.sudo().with_context(active_test=False)
        for rule in self.sudo():
            if not rule.active or not rule.product_ids:
                continue
            others = Rule.search([
                ('id', '!=', rule.id), ('active', '=', True),
                ('category_id', '=', rule.category_id.id),
                ('employee_id', '=', rule.employee_id.id or False),
            ])
            for other in others:
                overlapping_scope = (not rule.company_id or not other.company_id or rule.company_id == other.company_id)
                if overlapping_scope and (rule.product_ids & other.product_ids):
                    raise ValidationError(_(
                        'Active benefit rules overlap for the same employee, category and product. '
                        'Keep one default rule per product, or one rule per employee and product.'))

    @api.constrains('active', 'employee_id', 'product_ids', 'max_qty', 'timezone')
    def _check_active_rule(self):
        for rule in self.sudo():
            if not math.isfinite(rule.max_qty) or rule.max_qty <= 0:
                raise ValidationError(_('The daily benefit quantity must be greater than zero.'))
            if rule.active and not rule.product_ids:
                raise ValidationError(_('Select the eligible products before activating the benefit rule.'))
            try:
                pytz.timezone(rule.timezone)
            except (pytz.UnknownTimeZoneError, TypeError, AttributeError):
                raise ValidationError(_('Enter a valid company business timezone, such as Asia/Dhaka.')) from None
            if rule.active:
                if rule.employee_id and not rule.employee_id.active:
                    raise ValidationError(_('Select an active employee before activating the benefit rule.'))
                product_uoms = rule.product_ids.mapped('uom_id')
                if len(product_uoms) > 1:
                    raise ValidationError(_('Products in one daily allowance rule must use the same unit of measure.'))

    @api.model
    def _check_category_manager(self):
        if not (self.env.user.pos_markout_can_manage_categories or self.env.user.has_group('base.group_system')):
            raise AccessError(_('You do not have permission to manage benefit rules.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_category_manager()
        return super().create(vals_list)

    def write(self, vals):
        self._check_category_manager()
        return super().write(vals)

    def unlink(self):
        self._check_category_manager()
        return super().unlink()
