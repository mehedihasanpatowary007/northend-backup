import io
import pytz
from datetime import datetime
import xlsxwriter

from odoo import http
from odoo.http import request
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT


class PosWaiterCashierReportController(http.Controller):

    def _resolve_session_and_domain(self, config_id=None, session_id=None):
        env = request.env
        session = False
        config = False

        if session_id:
            try:
                session = env['pos.session'].browse(int(session_id))
                if not session.exists():
                    session = False
            except (ValueError, TypeError):
                session = False

        if not session and config_id:
            try:
                config = env['pos.config'].browse(int(config_id))
                if not config.exists():
                    config = False
            except (ValueError, TypeError):
                config = False
            if config:
                session = env['pos.session'].search([
                    ('config_id', '=', config.id),
                    ('state', 'in', ['opened', 'opening_control', 'closing_control']),
                ], order='id desc', limit=1)
                if not session:
                    session = env['pos.session'].search([('config_id', '=', config.id)], order='id desc', limit=1)

        if not session:
            session = env['pos.session'].search([
                ('state', 'in', ['opened', 'opening_control', 'closing_control']),
            ], order='id desc', limit=1)
            if not session:
                session = env['pos.session'].search([], order='id desc', limit=1)

        if session:
            config = session.config_id
            company = session.company_id or config.company_id or env.company
            orders = env['pos.order'].search([
                ('session_id', '=', session.id),
                ('state', 'in', ['paid', 'done', 'invoiced']),
            ])
        elif config:
            company = config.company_id or env.company
            orders = env['pos.order'].browse([])
        else:
            config = env['pos.config'].search([], limit=1)
            company = config.company_id if config else env.company
            orders = env['pos.order'].browse([])

        user_tz_name = env.user.tz or 'UTC'
        user_tz = pytz.timezone(user_tz_name)
        now_user = datetime.now(user_tz)

        if session and session.start_at:
            session_start_user = pytz.utc.localize(session.start_at).astimezone(user_tz)
            start_str = session_start_user.strftime('%d %B %Y %I:%M %p')
            if session.stop_at:
                session_stop_user = pytz.utc.localize(session.stop_at).astimezone(user_tz)
                stop_str = session_stop_user.strftime('%d %B %Y %I:%M %p')
            else:
                stop_str = 'In Progress'
            period_string = f"{start_str} - {stop_str}"
        else:
            today_start_user = now_user.replace(hour=0, minute=0, second=0, microsecond=0)
            period_string = f"{today_start_user.strftime('%d %B %Y 00:00')} - {now_user.strftime('%d %B %Y %H:%M')}"
            start_str = today_start_user.strftime('%d %B %Y 00:00')
            stop_str = now_user.strftime('%d %B %Y %H:%M')

        state_labels = {
            'opening_control': 'Opening Control',
            'opened': 'In Progress',
            'closing_control': 'Closing Control',
            'closed': 'Closed & Posted',
        }
        session_state_label = state_labels.get(session.state, session.state.title()) if session else 'N/A'

        return {
            'env': env,
            'session': session,
            'session_id': session.id if session else False,
            'session_name': session.name if session else '',
            'session_state': session_state_label,
            'session_user': session.user_id.name if session and session.user_id else '',
            'session_start_str': start_str,
            'session_stop_str': stop_str,
            'period_string': period_string,
            'config': config,
            'company': company,
            'user_tz': user_tz,
            'now_user': now_user,
            'orders': orders,
        }

    def _get_report_data(self, config_id=None, session_id=None):
        meta = self._resolve_session_and_domain(config_id=config_id, session_id=session_id)
        env = meta['env']
        config = meta['config']
        company = meta['company']
        now_user = meta['now_user']
        period_string = meta['period_string']
        orders = meta['orders']
        session = meta['session']

        # 1. Income by Payment Method / Gateway
        income_by_method = {}
        total_income = 0.0
        total_payment_count = 0

        for order in orders:
            for payment in order.payment_ids:
                pm = payment.payment_method_id
                pm_id = pm.id
                pm_name = pm.name or 'Other'
                # Chart of account / journal name if available
                account_name = pm.journal_id.default_account_id.name if pm.journal_id and pm.journal_id.default_account_id else ''
                display_name = f"{pm_name} ({account_name})" if account_name else pm_name

                if pm_id not in income_by_method:
                    income_by_method[pm_id] = {
                        'name': pm_name,
                        'display_name': display_name,
                        'count': 0,
                        'amount': 0.0,
                        'percentage': 0.0,
                    }
                income_by_method[pm_id]['count'] += 1
                income_by_method[pm_id]['amount'] += payment.amount
                total_income += payment.amount
                total_payment_count += 1

        # Calculate percentages
        income_list = list(income_by_method.values())
        for item in income_list:
            if total_income > 0:
                item['percentage'] = round((item['amount'] / total_income) * 100, 2)
            else:
                item['percentage'] = 0.0

        # Sort descending by amount
        income_list.sort(key=lambda x: x['amount'], reverse=True)

        # 2. User-wise breakdowns
        user_settlement = {}
        for order in orders:
            # Prefer employee name, fallback to user name
            user_name = order.employee_id.name if (hasattr(order, 'employee_id') and order.employee_id) else (order.user_id.name or 'Unknown')
            if user_name not in user_settlement:
                user_settlement[user_name] = {
                    'name': user_name,
                    'collection': 0.0,
                    'order_count': 0,
                    'percentage': 0.0,
                }
            user_settlement[user_name]['collection'] += order.amount_total
            user_settlement[user_name]['order_count'] += 1

        user_settlement_list = list(user_settlement.values())
        total_order_collection = sum(u['collection'] for u in user_settlement_list)
        total_tickets = sum(u['order_count'] for u in user_settlement_list)

        for u in user_settlement_list:
            if total_order_collection > 0:
                u['percentage'] = round((u['collection'] / total_order_collection) * 100, 2)
            else:
                u['percentage'] = 0.0

        user_settlement_list.sort(key=lambda x: x['collection'], reverse=True)

        return {
            'config': config,
            'company': company,
            'session': session,
            'session_id': meta['session_id'],
            'session_name': meta['session_name'],
            'session_state': meta['session_state'],
            'session_user': meta['session_user'],
            'period_string': period_string,
            'print_datetime': now_user.strftime('%A, %B %d, %Y %I:%M:%S %p'),
            'income_list': income_list,
            'total_payment_count': total_payment_count,
            'total_income': total_income,
            'user_settlement_list': user_settlement_list,
            'total_order_collection': total_order_collection,
            'total_tickets': total_tickets,
            'currency': config.currency_id if config else company.currency_id,
        }

    @http.route('/pos/waiter_cashier_report', type='http', auth='user', website=False)
    def waiter_cashier_report(self, config_id=None, session_id=None, **kwargs):
        data = self._get_report_data(config_id=config_id, session_id=session_id)
        response = request.render('zencore_pos_custom_report.report_waiter_cashier_template', data)
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    @http.route('/pos/waiter_cashier_report/export_xlsx', type='http', auth='user', website=False)
    def export_waiter_cashier_xlsx(self, config_id=None, session_id=None, **kwargs):
        data = self._get_report_data(config_id=config_id, session_id=session_id)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Waiter Cashier Report')

        # Formatting Styles
        title_format = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'center', 'valign': 'vcenter'
        })
        subtitle_format = workbook.add_format({
            'font_size': 10, 'align': 'center', 'valign': 'vcenter'
        })
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#707070', 'font_color': '#FFFFFF',
            'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        sub_header_format = workbook.add_format({
            'bold': True, 'bg_color': '#F2F2F2', 'border': 1, 'valign': 'vcenter'
        })
        cell_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        num_format = workbook.add_format({'border': 1, 'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0.00'})
        int_format = workbook.add_format({'border': 1, 'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0'})
        pct_format = workbook.add_format({'border': 1, 'align': 'right', 'valign': 'vcenter', 'num_format': '0.00"%"'})
        bold_total_num = workbook.add_format({
            'bold': True, 'border': 1, 'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0.00'
        })
        bold_total_int = workbook.add_format({
            'bold': True, 'border': 1, 'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0'
        })

        worksheet.set_column('A:A', 30)
        worksheet.set_column('B:B', 15)
        worksheet.set_column('C:C', 15)
        worksheet.set_column('D:D', 20)

        # Header Titles
        worksheet.merge_range('A1:D1', 'Waiter Cashier Report', title_format)
        sub_title = f"Session: {data['session_name']} | Period: {data['period_string']}" if data.get('session_name') else f"Period: {data['period_string']}"
        worksheet.merge_range('A2:D2', sub_title, subtitle_format)
        worksheet.merge_range('A3:D3', data['company'].name or '', subtitle_format)
        vat_info = f"Central BIN-{data['company'].vat or 'N/A'}"
        worksheet.merge_range('A4:D4', vat_info, subtitle_format)

        row = 6
        # Table 1: Incomes
        config_name = data['config'].name if data['config'] else 'Branch'
        worksheet.merge_range(row, 0, row, 3, f"{config_name} Incomes", header_format)
        row += 1

        for item in data['income_list']:
            worksheet.write(row, 0, item['name'], cell_format)
            worksheet.write(row, 1, item['count'], int_format)
            worksheet.write(row, 2, item['percentage'], pct_format)
            worksheet.write(row, 3, item['amount'], num_format)
            row += 1

        # Table 1 Totals
        worksheet.write(row, 0, f"{config_name} TOTAL INCOME", sub_header_format)
        worksheet.write(row, 1, data['total_payment_count'], bold_total_int)
        worksheet.write(row, 2, 100.0 if data['total_income'] > 0 else 0.0, pct_format)
        worksheet.write(row, 3, data['total_income'], bold_total_num)
        row += 3

        # Table 2: User Wise Settlement
        worksheet.merge_range(row, 0, row, 3, "User Wise Settlement", header_format)
        row += 1
        worksheet.write(row, 0, "User Name", sub_header_format)
        worksheet.write(row, 1, "", sub_header_format)
        worksheet.write(row, 2, "Collection", sub_header_format)
        worksheet.write(row, 3, "%", sub_header_format)
        row += 1

        for u in data['user_settlement_list']:
            worksheet.write(row, 0, u['name'], cell_format)
            worksheet.write(row, 1, "", cell_format)
            worksheet.write(row, 2, u['collection'], num_format)
            worksheet.write(row, 3, u['percentage'], pct_format)
            row += 1

        row += 2
        # Table 3: User Wise Order Collection
        worksheet.merge_range(row, 0, row, 3, "User Wise Order Collection", header_format)
        row += 1
        for u in data['user_settlement_list']:
            worksheet.write(row, 0, u['name'], cell_format)
            worksheet.write(row, 1, "", cell_format)
            worksheet.write(row, 2, u['collection'], num_format)
            worksheet.write(row, 3, u['percentage'], pct_format)
            row += 1

        row += 2
        # Table 4: User Wise Ticket Creation
        worksheet.merge_range(row, 0, row, 3, "User Wise Ticket Creation", header_format)
        row += 1
        for u in data['user_settlement_list']:
            worksheet.write(row, 0, u['name'], cell_format)
            worksheet.write(row, 1, "", cell_format)
            worksheet.write(row, 2, u['collection'], num_format)
            worksheet.write(row, 3, u['percentage'], pct_format)
            row += 1

        row += 2
        worksheet.write(row, 0, f"*** Computer generated report. Print Date Time: {data['print_datetime']}", subtitle_format)

        workbook.close()
        output.seek(0)
        xlsx_data = output.read()

        session_suffix = f"_{data['session_name'].replace('/', '_')}" if data.get('session_name') else ""
        filename = f"Waiter_Cashier_Report{session_suffix}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        headers = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', f'attachment; filename="{filename}"'),
        ]
        return request.make_response(xlsx_data, headers=headers)

    def _get_items_sales_data(self, config_id=None, session_id=None):
        meta = self._resolve_session_and_domain(config_id=config_id, session_id=session_id)
        env = meta['env']
        config = meta['config']
        company = meta['company']
        user_tz = meta['user_tz']
        now_user = meta['now_user']
        period_string = meta['period_string']
        orders = meta['orders']
        session = meta['session']
        print_datetime_str = now_user.strftime('%A, %B %d, %Y %I:%M:%S %p')

        order_lines = orders.mapped('lines')

        # 1. Aggregate sold products today
        product_sales = {}
        for line in order_lines:
            pid = line.product_id.id
            if pid not in product_sales:
                product_sales[pid] = {
                    'qty': 0.0,
                    'gross_amount': 0.0,
                    'net_amount': 0.0,
                    'price_unit': line.price_unit,
                }
            product_sales[pid]['qty'] += line.qty
            product_sales[pid]['gross_amount'] += line.price_subtotal_incl
            product_sales[pid]['net_amount'] += line.price_subtotal
            product_sales[pid]['price_unit'] = line.price_unit

        # 2. Get all products available in POS (plus any sold today)
        available_products = env['product.product'].search([('available_in_pos', '=', True)])
        sold_product_ids = set(product_sales.keys())
        all_product_ids = list(set(available_products.ids) | sold_product_ids)
        products = env['product.product'].browse(all_product_ids)

        # 3. Category data map
        category_data = {}
        for pc in env['pos.category'].search([]):
            category_data[pc.name] = {
                'name': pc.name,
                'gross': 0.0,
                'net': 0.0,
                'qty': 0.0,
                'percentage': 0.0,
                'qty_percentage': 0.0,
            }

        product_details = []
        for prod in products:
            # Determine category name
            categ_name = prod.product_tmpl_id.pos_categ_ids[0].name if prod.product_tmpl_id.pos_categ_ids else (prod.categ_id.name or 'Uncategorized')

            # Determine Portion (attribute/variant combination name or 'Normal')
            combo_name = prod.product_template_attribute_value_ids._get_combination_name()
            portion = combo_name if combo_name else 'Normal'

            base_product_name = prod.product_tmpl_id.name or prod.name

            sold_info = product_sales.get(prod.id, {
                'qty': 0.0,
                'gross_amount': 0.0,
                'net_amount': 0.0,
                'price_unit': prod.lst_price,
            })

            qty = sold_info['qty']
            gross_amt = sold_info['gross_amount']
            net_amt = sold_info['net_amount']
            price_unit = sold_info.get('price_unit', prod.lst_price) or prod.lst_price

            if categ_name not in category_data:
                category_data[categ_name] = {
                    'name': categ_name,
                    'gross': 0.0,
                    'net': 0.0,
                    'qty': 0.0,
                    'percentage': 0.0,
                    'qty_percentage': 0.0,
                }
            category_data[categ_name]['gross'] += gross_amt
            category_data[categ_name]['net'] += net_amt
            category_data[categ_name]['qty'] += qty

            product_details.append({
                'category': categ_name,
                'product': base_product_name,
                'portion': portion,
                'price': price_unit,
                'price_formatted': f"{price_unit:,.2f}",
                'qty': qty,
                'qty_formatted': f"{int(qty)}" if qty == int(qty) else f"{qty:,.2f}",
                'amount': gross_amt,
                'amount_formatted': f"{gross_amt:,.2f}",
            })

        # Totals for Category Groups
        total_group_gross = sum(c['gross'] for c in category_data.values())
        total_group_net = sum(c['net'] for c in category_data.values())
        total_group_qty = sum(c['qty'] for c in category_data.values())

        # Table 1: Sales by Item Group
        sales_by_group = list(category_data.values())
        for c in sales_by_group:
            pct = (c['gross'] / total_group_gross * 100) if total_group_gross > 0 else 0.0
            c['percentage'] = pct
            c['percentage_formatted'] = f"%{pct:.2f}"
            c['gross_formatted'] = f"{c['gross']:,.2f}"
            c['net_formatted'] = f"{c['net']:,.2f}"
        sales_by_group.sort(key=lambda x: (x['gross'] > 0, x['gross'], x['name']), reverse=True)

        # Table 2: Quantities by Item Group
        qty_by_group = [dict(c) for c in category_data.values()]
        for c in qty_by_group:
            q_pct = (c['qty'] / total_group_qty * 100) if total_group_qty > 0 else 0.0
            c['qty_percentage'] = q_pct
            c['qty_percentage_formatted'] = f"%{q_pct:.2f}"
            c['qty_formatted'] = f"{int(c['qty'])}" if c['qty'] == int(c['qty']) else f"{c['qty']:,.2f}"
        qty_by_group.sort(key=lambda x: (x['qty'] > 0, x['qty'], x['name']), reverse=True)

        # Table 3: Product Detail Breakdown (sort by category, active sales first, then product name)
        product_details.sort(key=lambda x: (x['category'].lower(), -(x['qty'] > 0), -x['qty'], x['product'].lower(), x['portion'].lower()))

        total_prod_qty = sum(p['qty'] for p in product_details)
        total_prod_amount = sum(p['amount'] for p in product_details)

        return {
            'config': config,
            'company': company,
            'session': session,
            'session_id': meta['session_id'],
            'session_name': meta['session_name'],
            'session_state': meta['session_state'],
            'session_user': meta['session_user'],
            'period_string': period_string,
            'print_datetime_str': print_datetime_str,
            'sales_by_group': sales_by_group,
            'qty_by_group': qty_by_group,
            'product_details': product_details,
            'total_group_gross': total_group_gross,
            'total_group_net': total_group_net,
            'total_group_qty': total_group_qty,
            'total_prod_qty': total_prod_qty,
            'total_prod_amount': total_prod_amount,
            'total_group_gross_formatted': f"{total_group_gross:,.2f}",
            'total_group_net_formatted': f"{total_group_net:,.2f}",
            'total_group_qty_formatted': f"{int(total_group_qty)}" if total_group_qty == int(total_group_qty) else f"{total_group_qty:,.2f}",
            'total_product_qty_formatted': f"{int(total_prod_qty)}" if total_prod_qty == int(total_prod_qty) else f"{total_prod_qty:,.2f}",
            'total_product_amount_formatted': f"{total_prod_amount:,.2f}",
        }

    @http.route('/pos/items_sales_report', type='http', auth='user')
    def items_sales_report(self, config_id=None, session_id=None, **kwargs):
        data = self._get_items_sales_data(config_id=config_id, session_id=session_id)
        response = request.render('zencore_pos_custom_report.report_items_sales_template', data)
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    @http.route('/pos/items_sales_report/export_xlsx', type='http', auth='user')
    def export_items_sales_xlsx(self, config_id=None, session_id=None, **kwargs):
        data = self._get_items_sales_data(config_id=config_id, session_id=session_id)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Item Sales Report')

        # Formats
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        subtitle_format = workbook.add_format({'font_size': 10, 'align': 'center'})
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#707070',
            'font_color': '#ffffff',
            'align': 'center',
            'border': 1,
            'font_size': 11,
        })
        sub_header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#707070',
            'font_color': '#ffffff',
            'align': 'center',
            'border': 1,
            'font_size': 10,
        })
        cell_format = workbook.add_format({'border': 1, 'font_size': 10, 'valign': 'vcenter'})
        cell_center = workbook.add_format({'border': 1, 'font_size': 10, 'align': 'center', 'valign': 'vcenter'})
        num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00', 'font_size': 10, 'align': 'right', 'valign': 'vcenter'})
        qty_format = workbook.add_format({'border': 1, 'num_format': '#,##0', 'font_size': 10, 'align': 'right', 'valign': 'vcenter'})
        pct_format = workbook.add_format({'border': 1, 'num_format': '0.00"%"', 'font_size': 10, 'align': 'right', 'valign': 'vcenter'})
        total_label_format = workbook.add_format({'bold': True, 'border': 1, 'font_size': 10, 'align': 'right', 'valign': 'vcenter'})
        total_num_format = workbook.add_format({'bold': True, 'border': 1, 'num_format': '#,##0.00', 'font_size': 10, 'align': 'right', 'valign': 'vcenter'})
        total_qty_format = workbook.add_format({'bold': True, 'border': 1, 'num_format': '#,##0', 'font_size': 10, 'align': 'right', 'valign': 'vcenter'})
        empty_border_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})

        worksheet.set_column('A:A', 24)
        worksheet.set_column('B:B', 28)
        worksheet.set_column('C:C', 16)
        worksheet.set_column('D:D', 14)
        worksheet.set_column('E:E', 15)
        worksheet.set_column('F:F', 18)

        # Header section
        worksheet.merge_range('A1:F1', "Item Sales Report", title_format)
        sub_title = f"Session: {data['session_name']} | Period: {data['period_string']}" if data.get('session_name') else f"Period: {data['period_string']}"
        worksheet.merge_range('A2:F2', sub_title, subtitle_format)
        company = data['company']
        config = data['config']
        comp_name = config.name if config else company.name
        worksheet.merge_range('A3:F3', comp_name, subtitle_format)
        addr = f"{company.partner_id.city or ''}, {company.partner_id.country_id.name or ''}"
        worksheet.merge_range('A4:F4', addr, subtitle_format)
        vat_info = f"Central BIN-{company.vat or '000466455-0100'}, MUSAK-6.3"
        worksheet.merge_range('A5:F5', vat_info, subtitle_format)

        row = 6
        # Table 1: Sales by Item Group (Spans across all 6 columns: A-C Name, D %, E Gross, F Net)
        worksheet.merge_range(row, 0, row, 5, "Sales by Item Group", header_format)
        row += 1
        for g in data['sales_by_group']:
            worksheet.merge_range(row, 0, row, 2, g['name'], cell_format)
            worksheet.write(row, 3, g['percentage'] / 100.0, pct_format)
            worksheet.write(row, 4, g['gross'], num_format)
            worksheet.write(row, 5, g['net'], num_format)
            row += 1
        worksheet.merge_range(row, 0, row, 2, "", empty_border_format)
        worksheet.write(row, 3, "Total", total_label_format)
        worksheet.write(row, 4, data['total_group_gross'], total_num_format)
        worksheet.write(row, 5, data['total_group_net'], total_num_format)
        row += 3

        # Table 2: Quantities by Item Group (Spans across all 6 columns: A-D Name, E %, F Qty)
        worksheet.merge_range(row, 0, row, 5, "Quantities by Item Group", header_format)
        row += 1
        for g in data['qty_by_group']:
            worksheet.merge_range(row, 0, row, 3, g['name'], cell_format)
            worksheet.write(row, 4, g['qty_percentage'] / 100.0, pct_format)
            worksheet.write(row, 5, g['qty'], qty_format)
            row += 1
        worksheet.merge_range(row, 0, row, 3, "Total", total_label_format)
        worksheet.write(row, 4, "", empty_border_format)
        worksheet.write(row, 5, data['total_group_qty'], total_qty_format)
        row += 3

        # Table 3: Product Detail Breakdown (Columns A-F)
        worksheet.write(row, 0, "Category", sub_header_format)
        worksheet.write(row, 1, "Product", sub_header_format)
        worksheet.write(row, 2, "Portion", sub_header_format)
        worksheet.write(row, 3, "Price", sub_header_format)
        worksheet.write(row, 4, "Quantity", sub_header_format)
        worksheet.write(row, 5, "Net-Amount", sub_header_format)
        row += 1

        for p in data['product_details']:
            worksheet.write(row, 0, p['category'], cell_format)
            worksheet.write(row, 1, p['product'], cell_format)
            worksheet.write(row, 2, p['portion'], cell_center)
            worksheet.write(row, 3, p['price'], num_format)
            worksheet.write(row, 4, p['qty'], qty_format)
            worksheet.write(row, 5, p['amount'], num_format)
            row += 1

        worksheet.merge_range(row, 0, row, 3, "Total", total_label_format)
        worksheet.write(row, 4, data['total_prod_qty'], total_qty_format)
        worksheet.write(row, 5, data['total_prod_amount'], total_num_format)
        row += 3

        worksheet.merge_range(row, 0, row, 5, f"*** This is computer generated report and does not require any signature", subtitle_format)
        row += 1
        worksheet.merge_range(row, 0, row, 5, f"Print Date Time: {data['print_datetime_str']}", subtitle_format)
        row += 1
        worksheet.merge_range(row, 0, row, 5, "Powered by: 3S", subtitle_format)

        workbook.close()
        output.seek(0)
        xlsx_data = output.read()

        session_suffix = f"_{data['session_name'].replace('/', '_')}" if data.get('session_name') else ""
        filename = f"Item_Sales_Report{session_suffix}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        headers = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', f'attachment; filename="{filename}"'),
        ]
        return request.make_response(xlsx_data, headers=headers)

    def _get_work_period_sales_summary_data(self, config_id=None, session_id=None):
        meta = self._resolve_session_and_domain(config_id=config_id, session_id=session_id)
        env = meta['env']
        config = meta['config']
        company = meta['company']
        user_tz = meta['user_tz']
        now_user = meta['now_user']
        period_string = meta['period_string']
        orders = meta['orders']
        session = meta['session']
        print_datetime_str = now_user.strftime('%A, %B %d, %Y %I:%M:%S %p')

        order_lines = orders.mapped('lines')

        sales_total = sum(order_lines.mapped('price_subtotal'))

        # Helper to classify tax name dynamically
        def get_tax_particulars(tax, line):
            raw_name = tax.name or f"{tax.amount}%"
            tax_amount_val = tax.amount
            amount_str = f"{int(tax_amount_val)}%" if tax_amount_val == int(tax_amount_val) else f"{tax_amount_val}%"
            is_sd = 'SD' in raw_name.upper() or 'SD' in (tax.tax_group_id.name or '').upper() or 'SUPPLEMENTARY' in raw_name.upper()
            is_mer = 'MER' in raw_name.upper() or any('MERCHANDISE' in (c.name or '').upper() or 'RETAIL' in (c.name or '').upper() for c in line.product_id.pos_categ_ids)
            if is_sd:
                return f"SD ({amount_str})", True, False
            elif is_mer:
                return f"VAT Mer ({amount_str})", False, True
            else:
                return f"VAT ({amount_str})", False, False

        summary_rows_map = {}
        table1_tax_map = {}
        all_taxed_orders = set()

        for line in order_lines:
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            if line.tax_ids_after_fiscal_position:
                line_taxes = line.tax_ids_after_fiscal_position.compute_all(
                    price, line.currency_id, line.qty, product=line.product_id, partner=line.order_id.partner_id or False
                )
                for t in line_taxes['taxes']:
                    tax_rec = env['account.tax'].browse(t['id'])
                    particulars, is_sd, is_mer = get_tax_particulars(tax_rec, line)
                    tax_amt = t['amount']
                    tax_base = t['base']
                    all_taxed_orders.add(line.order_id.id)

                    # Table 1 mapping
                    if particulars not in table1_tax_map:
                        table1_tax_map[particulars] = {
                            'name': particulars,
                            'amount': 0.0,
                            'order_ids': set(),
                            'is_sd': is_sd,
                        }
                    table1_tax_map[particulars]['amount'] += tax_amt
                    table1_tax_map[particulars]['order_ids'].add(line.order_id.id)

                    # Table 3 mapping
                    if particulars not in summary_rows_map:
                        summary_rows_map[particulars] = {
                            'particulars': particulars,
                            'order_ids': set(),
                            'net_sales': 0.0,
                            'sd': 0.0,
                            'vat': 0.0,
                            'sales_total': 0.0,
                            'is_sd': is_sd,
                        }
                    summary_rows_map[particulars]['order_ids'].add(line.order_id.id)
                    summary_rows_map[particulars]['net_sales'] += tax_base
                    if is_sd:
                        summary_rows_map[particulars]['sd'] += tax_amt
                    else:
                        summary_rows_map[particulars]['vat'] += tax_amt
                    summary_rows_map[particulars]['sales_total'] += (tax_base + tax_amt)

        # Table 1 lines
        tax_sales_lines = []
        for particulars, tinfo in table1_tax_map.items():
            t_count = len(tinfo['order_ids'])
            label = f"{particulars} ({t_count})"
            tax_sales_lines.append({
                'label': label,
                'amount': tinfo['amount'],
                'amount_formatted': f"{tinfo['amount']:,.2f}",
                'is_sd': tinfo['is_sd'],
            })
        tax_sales_lines.sort(key=lambda x: (not x['is_sd'], x['label']))

        # Auto Rounding calculation
        auto_round_neg_sum = 0.0
        auto_round_neg_orders = set()
        auto_round_pos_sum = 0.0
        auto_round_pos_orders = set()

        for order in orders:
            order_line_gross = sum(order.lines.mapped('price_subtotal_incl'))
            diff = order.amount_total - order_line_gross
            if diff > 0.005:
                auto_round_pos_sum += diff
                auto_round_pos_orders.add(order.id)
            elif diff < -0.005:
                auto_round_neg_sum += abs(diff)
                auto_round_neg_orders.add(order.id)

        auto_round_neg_count = len(auto_round_neg_orders)
        auto_round_pos_count = len(auto_round_pos_orders)
        auto_round_neg_formatted = f"{auto_round_neg_sum:,.2f}" if auto_round_neg_sum > 0.005 else "-"
        auto_round_pos_formatted = f"{auto_round_pos_sum:,.2f}" if auto_round_pos_sum > 0.005 else "-"

        grand_total = sum(orders.mapped('amount_total'))

        # Table 2: Incomes
        income_by_method = {}
        total_income = 0.0
        for order in orders:
            for payment in order.payment_ids:
                pm = payment.payment_method_id
                pm_id = pm.id
                pm_name = pm.name or 'Other'
                if pm_id not in income_by_method:
                    income_by_method[pm_id] = {
                        'name': pm_name,
                        'amount': 0.0,
                        'percentage': 0.0,
                    }
                income_by_method[pm_id]['amount'] += payment.amount
                total_income += payment.amount

        income_list = list(income_by_method.values())
        for item in income_list:
            pct = (item['amount'] / total_income * 100) if total_income > 0 else 0.0
            item['percentage'] = pct
            item['percentage_formatted'] = f"{pct:.2f}%"
            item['amount_formatted'] = f"{item['amount']:,.2f}"
        income_list.sort(key=lambda x: x['amount'], reverse=True)

        # Table 3: Summary rows
        summary_tax_rows = []
        for particulars, sinfo in summary_rows_map.items():
            tickets = len(sinfo['order_ids'])
            summary_tax_rows.append({
                'particulars': particulars,
                'tickets': tickets,
                'net_sales': sinfo['net_sales'],
                'net_sales_formatted': f"{sinfo['net_sales']:,.2f}",
                'sc_formatted': "-",
                'sd': sinfo['sd'],
                'sd_formatted': f"{sinfo['sd']:,.2f}" if sinfo['sd'] > 0 else "-",
                'vat': sinfo['vat'],
                'vat_formatted': f"{sinfo['vat']:,.2f}" if sinfo['vat'] > 0 else "-",
                'sales_total': sinfo['sales_total'],
                'sales_total_formatted': f"{sinfo['sales_total']:,.2f}",
                'is_sd': sinfo['is_sd'],
            })
        summary_tax_rows.sort(key=lambda x: (not x['is_sd'], x['particulars']))

        total_summary_tickets = len(all_taxed_orders)
        total_summary_net = sum(r['net_sales'] for r in summary_tax_rows)
        total_summary_sd = sum(r['sd'] for r in summary_tax_rows)
        total_summary_vat = sum(r['vat'] for r in summary_tax_rows)
        total_summary_sales_total = sum(r['sales_total'] for r in summary_tax_rows)

        return {
            'config': config,
            'company': company,
            'session': session,
            'session_id': meta['session_id'],
            'session_name': meta['session_name'],
            'session_state': meta['session_state'],
            'session_user': meta['session_user'],
            'period_string': period_string,
            'print_datetime_str': print_datetime_str,
            'sales_total': sales_total,
            'sales_total_formatted': f"{sales_total:,.2f}",
            'tax_sales_lines': tax_sales_lines,
            'auto_round_neg_count': auto_round_neg_count,
            'auto_round_neg_formatted': auto_round_neg_formatted,
            'auto_round_pos_count': auto_round_pos_count,
            'auto_round_pos_formatted': auto_round_pos_formatted,
            'grand_total': grand_total,
            'grand_total_formatted': f"{grand_total:,.2f}",
            'income_list': income_list,
            'total_income': total_income,
            'total_income_formatted': f"{total_income:,.2f}",
            'summary_tax_rows': summary_tax_rows,
            'total_summary_tickets': total_summary_tickets,
            'total_summary_net': total_summary_net,
            'total_summary_net_formatted': f"{total_summary_net:,.2f}",
            'total_summary_sd': total_summary_sd,
            'total_summary_sd_formatted': f"{total_summary_sd:,.2f}" if total_summary_sd > 0 else "-",
            'total_summary_vat': total_summary_vat,
            'total_summary_vat_formatted': f"{total_summary_vat:,.2f}",
            'total_summary_sales_total': total_summary_sales_total,
            'total_summary_sales_total_formatted': f"{total_summary_sales_total:,.2f}",
        }

    @http.route('/pos/work_period_sales_summary', type='http', auth='user')
    def work_period_sales_summary(self, config_id=None, session_id=None, **kwargs):
        data = self._get_work_period_sales_summary_data(config_id=config_id, session_id=session_id)
        response = request.render('zencore_pos_custom_report.report_work_period_sales_summary_template', data)
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    @http.route('/pos/work_period_sales_summary/export_xlsx', type='http', auth='user')
    def export_work_period_sales_summary_xlsx(self, config_id=None, session_id=None, **kwargs):
        data = self._get_work_period_sales_summary_data(config_id=config_id, session_id=session_id)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Work Period Sales Summary')

        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        subtitle_format = workbook.add_format({'font_size': 10, 'align': 'center'})
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#707070',
            'font_color': '#ffffff',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 11,
        })
        sub_header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#ffffff',
            'font_color': '#000000',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
        })
        sub_header_right = workbook.add_format({
            'bold': True,
            'bg_color': '#ffffff',
            'font_color': '#000000',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
        })
        cell_format = workbook.add_format({'border': 1, 'font_size': 10, 'valign': 'vcenter'})
        cell_center = workbook.add_format({'border': 1, 'font_size': 10, 'align': 'center', 'valign': 'vcenter'})
        num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00', 'font_size': 10, 'align': 'right', 'valign': 'vcenter'})
        int_format = workbook.add_format({'border': 1, 'num_format': '#,##0', 'font_size': 10, 'align': 'center', 'valign': 'vcenter'})
        pct_format = workbook.add_format({'border': 1, 'num_format': '0.00"%"', 'font_size': 10, 'align': 'right', 'valign': 'vcenter'})
        total_label_format = workbook.add_format({'bold': True, 'border': 1, 'font_size': 10, 'valign': 'vcenter'})
        total_num_format = workbook.add_format({'bold': True, 'border': 1, 'num_format': '#,##0.00', 'font_size': 10, 'align': 'right', 'valign': 'vcenter'})
        total_int_format = workbook.add_format({'bold': True, 'border': 1, 'num_format': '#,##0', 'font_size': 10, 'align': 'center', 'valign': 'vcenter'})
        empty_border_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        text_center_format = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10})

        worksheet.set_column('A:A', 26)
        worksheet.set_column('B:B', 12)
        worksheet.set_column('C:C', 16)
        worksheet.set_column('D:D', 10)
        worksheet.set_column('E:E', 15)
        worksheet.set_column('F:F', 15)
        worksheet.set_column('G:G', 18)

        # Header section
        worksheet.merge_range('A1:G1', "Work Period Sales Summary Report", title_format)
        sub_title = f"Session: {data['session_name']} | Period: {data['period_string']}" if data.get('session_name') else f"Period: {data['period_string']}"
        worksheet.merge_range('A2:G2', sub_title, subtitle_format)
        company = data['company']
        config = data['config']
        comp_name = config.name if config else company.name
        worksheet.merge_range('A3:G3', comp_name, subtitle_format)
        addr = f"{company.partner_id.city or ''}, {company.partner_id.country_id.name or ''}"
        worksheet.merge_range('A4:G4', addr, subtitle_format)
        vat_info = f"Central BIN-{company.vat or '000466455-0100'}, MUSAK-6.3"
        worksheet.merge_range('A5:G5', vat_info, subtitle_format)

        row = 6
        # Table 1: Sales
        worksheet.merge_range(row, 0, row, 6, "Sales", header_format)
        row += 1
        worksheet.merge_range(row, 0, row, 4, "", sub_header_format)
        worksheet.merge_range(row, 5, row, 6, "Net Total", sub_header_right)
        row += 1

        worksheet.merge_range(row, 0, row, 4, "SALES TOTAL", cell_format)
        worksheet.merge_range(row, 5, row, 6, data['sales_total'], num_format)
        row += 1

        for tline in data['tax_sales_lines']:
            worksheet.merge_range(row, 0, row, 4, tline['label'], cell_format)
            worksheet.merge_range(row, 5, row, 6, tline['amount'], num_format)
            row += 1

        worksheet.merge_range(row, 0, row, 4, f"Auto Round - ({data['auto_round_neg_count']})", cell_format)
        worksheet.merge_range(row, 5, row, 6, data['auto_round_neg_formatted'], cell_format if data['auto_round_neg_formatted'] == '-' else num_format)
        row += 1

        worksheet.merge_range(row, 0, row, 4, f"Auto Round + ({data['auto_round_pos_count']})", cell_format)
        worksheet.merge_range(row, 5, row, 6, data['auto_round_pos_formatted'], cell_format if data['auto_round_pos_formatted'] == '-' else num_format)
        row += 1

        worksheet.merge_range(row, 0, row, 4, "GRAND TOTAL", total_label_format)
        worksheet.merge_range(row, 5, row, 6, data['grand_total'], total_num_format)
        row += 3

        # Table 2: Incomes
        worksheet.merge_range(row, 0, row, 6, "Incomes", header_format)
        row += 1
        for item in data['income_list']:
            worksheet.merge_range(row, 0, row, 3, item['name'], cell_format)
            worksheet.write(row, 4, item['percentage'] / 100.0, pct_format)
            worksheet.merge_range(row, 5, row, 6, item['amount'], num_format)
            row += 1

        worksheet.merge_range(row, 0, row, 3, "TOTAL INCOME", total_label_format)
        worksheet.write(row, 4, "", empty_border_format)
        worksheet.merge_range(row, 5, row, 6, data['total_income'], total_num_format)
        row += 3

        # Table 3: Sales Summary Report
        worksheet.merge_range(row, 0, row, 6, "Sales Summary Report", header_format)
        row += 1
        worksheet.write(row, 0, "Particulars", sub_header_format)
        worksheet.write(row, 1, "Tickets", sub_header_format)
        worksheet.write(row, 2, "Net Sales", sub_header_format)
        worksheet.write(row, 3, "SC", sub_header_format)
        worksheet.write(row, 4, "SD", sub_header_format)
        worksheet.write(row, 5, "VAT", sub_header_format)
        worksheet.write(row, 6, "Sales Total", sub_header_format)
        row += 1

        for srow in data['summary_tax_rows']:
            worksheet.write(row, 0, srow['particulars'], cell_format)
            worksheet.write(row, 1, srow['tickets'], int_format)
            worksheet.write(row, 2, srow['net_sales'], num_format)
            worksheet.write(row, 3, "-", text_center_format)
            if srow['sd'] > 0:
                worksheet.write(row, 4, srow['sd'], num_format)
            else:
                worksheet.write(row, 4, "-", text_center_format)
            worksheet.write(row, 5, srow['vat'], num_format)
            worksheet.write(row, 6, srow['sales_total'], num_format)
            row += 1

        worksheet.write(row, 0, "Total", total_label_format)
        worksheet.write(row, 1, data['total_summary_tickets'], total_int_format)
        worksheet.write(row, 2, data['total_summary_net'], total_num_format)
        worksheet.write(row, 3, "-", text_center_format)
        if data['total_summary_sd'] > 0:
            worksheet.write(row, 4, data['total_summary_sd'], total_num_format)
        else:
            worksheet.write(row, 4, "-", text_center_format)
        worksheet.write(row, 5, data['total_summary_vat'], total_num_format)
        worksheet.write(row, 6, data['total_summary_sales_total'], total_num_format)
        row += 3

        # Cash & Card Summary Section Banner
        worksheet.merge_range(row, 0, row, 6, "Cash & Card Summary", header_format)
        row += 3

        worksheet.merge_range(row, 0, row, 6, f"*** This is computer generated report and does not require any signature", subtitle_format)
        row += 1
        worksheet.merge_range(row, 0, row, 6, f"Print Date Time: {data['print_datetime_str']}", subtitle_format)
        row += 1
        worksheet.merge_range(row, 0, row, 6, "Powered by: 3S", subtitle_format)

        workbook.close()
        output.seek(0)
        xlsx_data = output.read()

        session_suffix = f"_{data['session_name'].replace('/', '_')}" if data.get('session_name') else ""
        filename = f"Work_Period_Sales_Summary{session_suffix}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        headers = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', f'attachment; filename="{filename}"'),
        ]
        return request.make_response(xlsx_data, headers=headers)
