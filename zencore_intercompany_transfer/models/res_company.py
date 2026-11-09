from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    in_transit_valuation_account_id = fields.Many2one(
        'account.account', string='Inter-Company In-Transit Valuation Account',
        check_company=True, ondelete='restrict',
        groups='stock.group_stock_manager',
        domain="[('company_ids', 'in', id), ('account_type', '=', 'asset_current')]",
    )
    intercompany_receipt_type_id = fields.Many2one(
        'stock.picking.type', string='Inter-Company Receiving Operation',
        check_company=True, ondelete='restrict',
        groups='stock.group_stock_manager',
        domain="[('company_id', '=', id), ('code', '=', 'internal')]",
        help='Existing internal operation type whose default destination is the receiving stock location.',
    )

    @api.constrains('in_transit_valuation_account_id', 'intercompany_receipt_type_id')
    def _check_intercompany_configuration(self):
        for company in self:
            account = company.in_transit_valuation_account_id
            operation = company.intercompany_receipt_type_id
            if account and (company not in account.company_ids or account.account_type != 'asset_current'):
                raise ValidationError(_('The transit account must be a current asset account of this company.'))
            if operation and (
                operation.company_id != company or operation.code != 'internal'
                or operation.default_location_dest_id.usage != 'internal'
                or operation.default_location_dest_id.company_id != company
            ):
                raise ValidationError(_('Choose an internal operation with a destination stock location in this company.'))

    def write(self, vals):
        if {'in_transit_valuation_account_id', 'intercompany_receipt_type_id'} & vals.keys():
            if not self.env.su and not self.env.user.has_group('stock.group_stock_manager'):
                raise AccessError(_('Only an Inventory Administrator can change inter-company settings.'))
        return super().write(vals)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    in_transit_valuation_account_id = fields.Many2one(
        related='company_id.in_transit_valuation_account_id', readonly=False,
        groups='stock.group_stock_manager',
    )
    intercompany_receipt_type_id = fields.Many2one(
        related='company_id.intercompany_receipt_type_id', readonly=False,
        groups='stock.group_stock_manager',
    )
