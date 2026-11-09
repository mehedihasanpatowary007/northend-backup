from odoo import api, models, _
from odoo.exceptions import UserError


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            move = self.env['stock.move'].browse(vals.get('move_id'))
            if move.state == 'done' and move.picking_id.is_intercompany_transfer:
                raise UserError(_('Completed inter-company operations are locked. Use a Return.'))
        return super().create(vals_list)

    def write(self, vals):
        frozen = {'quantity', 'product_uom_id', 'product_id', 'lot_id', 'lot_name', 'owner_id',
                  'location_id', 'location_dest_id', 'move_id', 'picking_id', 'company_id',
                  'package_id', 'result_package_id', 'picked'}
        if frozen & vals.keys():
            for line in self.filtered(lambda line: line.state == 'done' and line.picking_id.is_intercompany_transfer):
                for key in frozen & vals.keys():
                    old = line[key].id if line._fields[key].type == 'many2one' else line[key]
                    if old != vals[key]:
                        raise UserError(_('Completed inter-company operations are locked. Use a Return.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _ict_protect_done_lines(self):
        if any(line.state == 'done' and line.picking_id.is_intercompany_transfer for line in self):
            raise UserError(_('Completed inter-company operations cannot be deleted.'))
