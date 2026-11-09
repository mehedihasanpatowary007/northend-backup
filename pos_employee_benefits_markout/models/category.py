import uuid

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class PosMarkoutCategory(models.Model):
    _name = 'pos.markout.category'
    _description = 'POS Marked Out Category'
    _inherit = ['mail.thread']
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    icon = fields.Selection([
        ('fa-gift', 'Gift / Benefit'),
        ('fa-users', 'People / Staff'),
        ('fa-coffee', 'Coffee / Cafe'),
        ('fa-building-o', 'Office / Corporate'),
        ('fa-cutlery', 'Food / Dining'),
        ('fa-graduation-cap', 'Training / Learning'),
        ('fa-flask', 'Testing / Development'),
        ('fa-leaf', 'Leaf / Sustainability'),
        ('fa-star', 'Star / Special'),
        ('fa-wrench', 'Tools / Maintenance'),
        ('fa-briefcase', 'Business'),
        ('fa-truck', 'Delivery / Suppliers'),
    ], string='Icon', required=True, default='fa-gift', tracking=True,
        help='Choose the icon shown on this main category tab in Marked Out.')
    code = fields.Char(
        string='Technical Reference', required=True, index=True, copy=False,
        default=lambda self: 'markout.%s' % uuid.uuid4().hex,
        help='Generated automatically. Existing references are kept when a category is renamed or moved.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    parent_id = fields.Many2one(
        'pos.markout.category', string='Parent Category', index=True, ondelete='restrict', check_company=True,
        help='Leave empty for a main category. Choose a main category to create a subcategory used in the POS.')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('pos.markout.category', 'parent_id', string='Subcategories')
    company_id = fields.Many2one('res.company', index=True, ondelete='cascade')
    product_ids = fields.Many2many(
        'product.product', 'pos_markout_category_product_rel', 'category_id', 'product_id',
        string='Allowed Products',
        help='Optional. Leave empty to allow every active, saleable product available in this POS.')
    stock_policy = fields.Selection([
        ('unconfigured', 'Needs Stock Setup'),
        ('prepare', 'Prepare Product (MO + Consumption)'),
        ('consume', 'Write Off Existing Stock'),
        ('restock', 'Return Existing Stock'),
        ('none', 'No Stock Movement'),
    ], string='Inventory Flow', required=True, default='prepare', tracking=True,
        help='Prepare Product makes products from their manufacturing recipe, then issues them once. '
             'Write Off and Return handle products that already exist; they never create a new MO.')
    stock_location_id = fields.Many2one(
        'stock.location', string='Stock Loss / Return Source',
        domain="[('usage', 'in', ['inventory', 'customer', 'supplier', 'transit'])]",
        help='Optional for Prepare Product: defaults to the product inventory-loss location. '
             'For Write Off Existing Stock, select an Inventory loss location. '
             'For Return Existing Stock, select the approved source of returned items.')
    _unique_code_scope = models.Constraint('unique(code, company_id)', 'Category technical codes must be unique per company.')

    @api.constrains('code', 'company_id')
    def _check_code_scope(self):
        for category in self:
            duplicate = self.sudo().with_context(active_test=False).search([
                ('id', '!=', category.id), ('code', '=', category.code),
                ('company_id', '=', category.company_id.id or False),
            ], limit=1)
            if duplicate:
                raise ValidationError(_('Category technical codes must be unique per company, including global categories.'))

    @api.constrains('parent_id', 'company_id', 'child_ids')
    def _check_hierarchy_company(self):
        # Include archived children and records hidden by company rules when a
        # parent is moved or its company changes. The structure has two levels.
        categories = self.sudo().with_context(active_test=False)
        categories |= categories.mapped('child_ids')
        for category in categories:
            parent = category.parent_id
            if parent and (parent == category or parent.parent_id or category.child_ids):
                raise ValidationError(_('Use only two levels: a main category and its subcategories. A category with subcategories cannot become a subcategory.'))
            if parent.company_id and category.company_id != parent.company_id:
                raise ValidationError(_('A subcategory under a company-specific category must use the same company. Leave the parent company empty to share the main category across companies.'))

    @api.constrains('stock_policy', 'stock_location_id')
    def _check_stock_destination(self):
        for category in self:
            location = category.stock_location_id
            if category.stock_policy in ('consume', 'restock') and not location:
                raise ValidationError(_('Choose the approved stock location for this category before enabling its stock policy.'))
            if category.stock_policy in ('prepare', 'consume') and location and location.usage != 'inventory':
                raise ValidationError(_('Prepared items and write-offs require an Inventory usage destination.'))
            if category.stock_policy == 'restock' and location and location.usage not in ('inventory', 'customer', 'supplier', 'transit'):
                raise ValidationError(_('Restock source must be an approved non-internal stock location.'))

    @api.model
    def _check_category_manager(self):
        if not (self.env.user.pos_markout_can_manage_categories or self.env.user.has_group('base.group_system')):
            raise AccessError(_('You do not have permission to manage Marked Out categories and benefit rules.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_category_manager()
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = 'markout.%s' % uuid.uuid4().hex
        return super().create(vals_list)

    def write(self, vals):
        self._check_category_manager()
        return super().write(vals)

    def unlink(self):
        self._check_category_manager()
        return super().unlink()
