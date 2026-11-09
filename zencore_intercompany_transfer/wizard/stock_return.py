from odoo import models, _
from odoo.exceptions import UserError


class StockReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    def _prepare_picking_default_values_based_on(self, picking):
        vals = super()._prepare_picking_default_values_based_on(picking)
        if picking.is_intercompany_transfer:
            if not picking.source_intercompany_picking_id:
                raise UserError(_('Receive the dispatched goods first, then create a Return from the receiving transfer.'))
            # Return from company B is a fresh dispatch to A, with its own linked receiving leg.
            vals.update({
                'picking_type_id': picking.picking_type_id.id,
                'partner_id': picking.source_intercompany_picking_id.sudo().company_id.partner_id.id,
                'location_id': picking.location_dest_id.id,
                'location_dest_id': picking.location_id.id,
            })
        return vals
