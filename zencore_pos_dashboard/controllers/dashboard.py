import calendar
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request


class PosDashboardController(http.Controller):
    @http.route('/pos_dashboard/data', type='json', auth='user')
    def data(self, date_from=None, date_to=None, config_id=None, **kwargs):
        try:
            current_start = datetime.strptime(date_from, '%Y-%m-%d') if date_from else datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            current_end = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1) if date_to else datetime.now() + timedelta(days=1)
        except (TypeError, ValueError):
            current_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            current_end = datetime.now() + timedelta(days=1)
        period_length = current_end - current_start
        previous_start = current_start - period_length

        def prorated_target(monthly_target):
            monthly_target = float(monthly_target or 0.0)
            if monthly_target <= 0:
                return 0.0
            total = 0.0
            cursor = current_start
            while cursor < current_end:
                days_in_month = calendar.monthrange(cursor.year, cursor.month)[1]
                next_month = (datetime(cursor.year + 1, 1, 1) if cursor.month == 12 else datetime(cursor.year, cursor.month + 1, 1))
                segment_end = min(current_end, next_month)
                total += monthly_target * (segment_end - cursor).total_seconds() / 86400 / days_in_month
                cursor = segment_end
            return total
        domain = [('state', 'in', ('paid', 'done', 'invoiced')), ('date_order', '>=', previous_start), ('date_order', '<', current_end)]
        if config_id:
            domain.append(('session_id.config_id', '=', int(config_id)))
        allowed_company_ids = request.env.user.company_ids.ids or [request.env.company.id]
        orders = request.env['pos.order'].with_context(allowed_company_ids=allowed_company_ids).search(domain, order='date_order desc', limit=10000)
        currency = request.env.company.currency_id

        def convert_amount(value, source_currency, company, date_order):
            value = float(value or 0.0)
            if not source_currency or source_currency == currency:
                return value
            return source_currency._convert(value, currency, company or request.env.company, date_order.date() if date_order else None)

        def serialize(order):
            employee = getattr(order, 'employee_id', False) or order.user_id
            config = order.session_id.config_id
            company = config.company_id or request.env.company
            source_currency = getattr(config, 'currency_id', False) or company.currency_id
            officer_name = employee.name if employee else '-'
            lines = []
            discount_total = 0.0
            for line in order.lines:
                product = line.product_id
                category = product.pos_categ_ids[:1].name if product.pos_categ_ids else (product.categ_id.name or 'Uncategorized')
                discount_total += convert_amount(abs(line.price_unit * line.qty) * (line.discount or 0.0) / 100.0, source_currency, company, order.date_order)
                lines.append({'product': product.display_name or product.name, 'category': category, 'qty': line.qty, 'amount': convert_amount(line.price_subtotal_incl, source_currency, company, order.date_order), 'image': f'/web/image/product.product/{product.id}/image_128' if product.image_128 else ''})
            return {
                'id': order.id,
                'name': order.name,
                'date': order.date_order.strftime('%Y-%m-%d %H:%M') if order.date_order else '',
                'timestamp': order.date_order.strftime('%Y-%m-%dT%H:%M:%S') if order.date_order else '',
                'customer': order.partner_id.name or 'Walk-in',
                'employee': officer_name,
                'officer_id': employee.id if employee else 0,
                'register': order.session_id.config_id.name or '-',
                'branch': company.name or request.env.company.name,
                'company_id': company.id,
                'session': order.session_id.name or '-',
                'session_id': order.session_id.id or 0,
                'amount': convert_amount(order.amount_total, source_currency, company, order.date_order),
                'discount': discount_total,
                'outlet_target': prorated_target(convert_amount(getattr(config, 'dashboard_monthly_target', 0.0), source_currency, company, current_start)),
                'officer_target': prorated_target(getattr(employee, 'dashboard_monthly_target', 0.0)),
                'payment': ', '.join(order.payment_ids.mapped('payment_method_id.name')) or '-',
                'payment_names': order.payment_ids.mapped('payment_method_id.name'),
                'payment_lines': [{'name': payment.payment_method_id.name or '-', 'amount': convert_amount(payment.amount, source_currency, company, order.date_order)} for payment in order.payment_ids],
                'state': order.state,
                'lines': lines,
            }
        rows = []
        for order in orders:
            row = serialize(order)
            row['period'] = 'current' if current_start <= order.date_order < current_end else 'previous'
            rows.append(row)

        outlet_targets = {}
        officer_targets = {}
        for row in rows:
            if row['period'] != 'current' or float(row['amount'] or 0) < 0:
                continue
            outlet = outlet_targets.setdefault(row['register'], {'name': row['register'], 'actual': 0.0, 'target': row['outlet_target']})
            outlet['actual'] += max(0.0, float(row['amount'] or 0))
            officer_key = row['officer_id'] or row['employee']
            officer = officer_targets.setdefault(officer_key, {'name': row['employee'], 'actual': 0.0, 'target': row['officer_target']})
            officer['actual'] += max(0.0, float(row['amount'] or 0))

        def finish_target(entry):
            entry['achievement'] = entry['actual'] / entry['target'] * 100 if entry['target'] else 0.0
            return entry

        targets = {
            'outlets': [finish_target(entry) for entry in outlet_targets.values()],
            'officers': [finish_target(entry) for entry in officer_targets.values()],
        }
        return {'currency': currency.symbol or currency.name, 'orders': rows, 'targets': targets, 'filters': {
            'registers': sorted({row['register'] for row in rows}),
            'employees': sorted({row['employee'] for row in rows}),
            'categories': sorted({line['category'] for row in rows for line in row['lines']}),
            'payments': sorted({row['payment'] for row in rows}),
        }}
