import hmac
from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain


class PosSession(models.Model):
    _inherit = 'pos.session'

    def authorize_settlement_bill(self, employee_id, pin):
        """Check native employee credentials for one print, without saving PINs.

        Normal credential failures return a denial instead of raising so the
        transaction commits the failed-attempt counter and temporary lock.
        An authorization never records a payment or changes the POS order.
        """
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only Point of Sale users can print settlement bills.'))
        self.check_access('read')
        session = self.exists()
        if not session:
            raise UserError(_('The POS session no longer exists.'))
        config = session.config_id
        if session.state != 'opened' or config.current_session_id != session:
            raise UserError(_('Settlement bills require the current open POS session.'))
        if session.company_id not in self.env.companies:
            raise AccessError(_('This POS is outside your allowed companies.'))
        if not config.module_pos_hr:
            return {
                'authorized': False,
                'error': _('Enable employee login on this POS before printing settlement bills.'),
            }
        if isinstance(employee_id, bool) or not isinstance(employee_id, int) or employee_id <= 0:
            return {
                'authorized': False,
                'error': _('Select an authorized POS employee before printing.'),
            }

        # Use the same employee domain as native POS login, with explicit
        # active/company constraints before accessing private credentials.
        domain = Domain.AND([
            config._employee_domain(self.env.uid),
            [('id', '=', employee_id), ('active', '=', True),
             ('company_id', '=', session.company_id.id)],
        ])
        employee = self.env['hr.employee'].sudo().search(domain, limit=1)
        if not employee or not employee.pos_settlement_bill_allowed:
            return {
                'authorized': False,
                'error': _('This employee does not have permission to print settlement bills.'),
            }

        # Serialize attempts across workers/tabs. The counter stays private and
        # is refreshed after locking because permission reads can prefetch it.
        self.env.cr.execute('SELECT id FROM hr_employee WHERE id = %s FOR UPDATE', [employee.id])
        employee.invalidate_recordset([
            'pos_settlement_pin_failures', 'pos_settlement_pin_locked_until',
            'pin', 'pos_settlement_bill_allowed', 'active', 'company_id',
        ])
        if (not employee.active or not employee.pos_settlement_bill_allowed
                or employee.company_id != session.company_id):
            return {
                'authorized': False,
                'error': _('This employee does not have permission to print settlement bills.'),
            }
        now = fields.Datetime.now()
        locked_until = employee.pos_settlement_pin_locked_until
        if locked_until and locked_until > now:
            return {
                'authorized': False,
                'error': _('Too many incorrect PIN attempts. Please try again in one minute.'),
            }
        if not employee.pin:
            return {
                'authorized': False,
                'error': _('Set this employee\'s existing Odoo PIN before printing settlement bills.'),
            }

        valid_format = isinstance(pin, str) and 0 < len(pin) <= 64 and pin.isdigit()
        valid_pin = valid_format and hmac.compare_digest(
            employee.pin.encode('utf-8'), pin.encode('utf-8'),
        )
        if not valid_pin:
            failures = 0 if locked_until else employee.pos_settlement_pin_failures
            failures += 1
            values = {
                'pos_settlement_pin_failures': failures,
                'pos_settlement_pin_locked_until': False,
            }
            if failures >= 5:
                values['pos_settlement_pin_locked_until'] = now + timedelta(seconds=60)
            employee.write(values)
            return {
                'authorized': False,
                'error': _('Incorrect employee PIN. Please try again.'),
            }

        if employee.pos_settlement_pin_failures or locked_until:
            employee.write({
                'pos_settlement_pin_failures': 0,
                'pos_settlement_pin_locked_until': False,
            })
        return {
            'authorized': True,
            'employee_name': employee.name,
            'printed_at': fields.Datetime.to_string(now),
        }
