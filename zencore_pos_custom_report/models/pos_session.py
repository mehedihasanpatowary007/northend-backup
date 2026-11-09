import io
import base64
import pytz
import logging
import xlsxwriter
from datetime import datetime

from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    def action_open_waiter_cashier_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/pos/waiter_cashier_report?session_id={self.id}&config_id={self.config_id.id}',
            'target': 'new',
        }

    def action_open_items_sales_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/pos/items_sales_report?session_id={self.id}&config_id={self.config_id.id}',
            'target': 'new',
        }

    def action_open_work_period_sales_summary(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/pos/work_period_sales_summary?session_id={self.id}&config_id={self.config_id.id}',
            'target': 'new',
        }

    def _get_pos_admin_recipients(self):
        """Find active users belonging to the POS Administrator group with valid emails."""
        self.ensure_one()
        group = self.env.ref('point_of_sale.group_pos_manager', raise_if_not_found=False)
        if not group:
            return []
        users = group.user_ids.filtered(
            lambda u: u.active and u.email and (not u.company_ids or self.company_id in u.company_ids)
        )
        return list(set(u.email.strip() for u in users if u.email.strip()))

    def _get_closing_summary_data(self):
        """Compile session closing summary tables strictly isolated to this session and card."""
        self.ensure_one()
        user_tz_name = self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(user_tz_name)
        now_user = datetime.now(user_tz)

        if self.start_at:
            session_start_user = pytz.utc.localize(self.start_at).astimezone(user_tz)
            start_str = session_start_user.strftime('%A, %d %B, %Y %I:%M %p')
        else:
            start_str = now_user.strftime('%A, %d %B, %Y 00:00')

        if self.stop_at:
            session_stop_user = pytz.utc.localize(self.stop_at).astimezone(user_tz)
            stop_str = session_stop_user.strftime('%A, %d %B, %Y %I:%M %p')
        else:
            stop_str = now_user.strftime('%A, %d %B, %Y %I:%M %p')

        work_period_str = f"Work Period Considered From: {start_str} TO {stop_str}"

        # Strict Session & Card Isolation
        orders = self.env['pos.order'].search([
            ('session_id', '=', self.id),
            ('state', 'in', ['paid', 'done', 'invoiced']),
        ])
        order_lines = orders.mapped('lines')

        # 1. Department Wise Sales (Card / Register Name)
        dept_name = self.config_id.name or 'Counter'
        sales_total = sum(order_lines.mapped('price_subtotal'))
        dept_sales_rows = [{'name': dept_name, 'value': sales_total}]

        # 2. Information Metrics
        net_total = sales_total
        grand_total = sum(orders.mapped('amount_total'))
        ticket_count = len(orders)
        guest_count = sum(getattr(o, 'customer_count', 0) for o in orders)
        grand_per_ticket = (grand_total / ticket_count) if ticket_count > 0 else 0.0
        sales_per_ticket = (sales_total / ticket_count) if ticket_count > 0 else 0.0
        grand_per_guest = (grand_total / guest_count) if guest_count > 0 else 0.0
        sales_per_guest = (sales_total / guest_count) if guest_count > 0 else 0.0

        info_rows = [
            ('SALES TOTAL', f"{sales_total:,.2f}"),
            ('NET TOTAL', f"{net_total:,.2f}"),
            ('GRAND TOTAL (Including Vat)', f"{grand_total:,.2f}"),
            ('TICKET COUNT', f"{ticket_count:.2f}"),
            ('NUMBER OF GUESTS', f"{guest_count:.2f}"),
            ('Grand Total / Ticket', f"{grand_per_ticket:,.2f}"),
            ('Sales Total / Ticket', f"{sales_per_ticket:,.2f}"),
            ('Grand Total / Guest', f"{grand_per_guest:,.2f}"),
            ('Sales Total / Guest', f"{sales_per_guest:,.2f}"),
        ]

        # 3. Accounts & Taxes
        discount_total = sum(
            (line.price_unit * line.qty * (line.discount or 0.0) / 100.0)
            for line in order_lines
        )

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

        tax_breakdown = {}
        for line in order_lines:
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            if line.tax_ids_after_fiscal_position:
                line_taxes = line.tax_ids_after_fiscal_position.compute_all(
                    price, line.currency_id, line.qty, product=line.product_id, partner=line.order_id.partner_id or False
                )
                for t in line_taxes['taxes']:
                    tax_rec = self.env['account.tax'].browse(t['id'])
                    particulars, is_sd, is_mer = get_tax_particulars(tax_rec, line)
                    if particulars not in tax_breakdown:
                        tax_breakdown[particulars] = {'name': particulars, 'amount': 0.0, 'is_sd': is_sd}
                    tax_breakdown[particulars]['amount'] += t['amount']

        # Auto Rounding calculation
        auto_round_sum = 0.0
        for order in orders:
            order_line_gross = sum(order.lines.mapped('price_subtotal_incl'))
            diff = order.amount_total - order_line_gross
            if abs(diff) > 0.005:
                auto_round_sum += diff

        accounts_rows = [
            ('Sales', f"{sales_total:,.2f}"),
            ('Discount', f"{discount_total:,.2f}"),
        ]
        # Append taxes sorted
        tax_list = list(tax_breakdown.values())
        tax_list.sort(key=lambda x: (not x['is_sd'], x['name']))
        for t in tax_list:
            accounts_rows.append((t['name'], f"{t['amount']:,.2f}"))
        accounts_rows.append(('Round', f"{auto_round_sum:,.2f}"))

        # 4. Payment Accounts Breakdown
        income_by_method = {}
        total_payments = 0.0
        for order in orders:
            for payment in order.payment_ids:
                pm = payment.payment_method_id
                pm_id = pm.id
                pm_name = pm.name or 'Other'
                if pm_id not in income_by_method:
                    income_by_method[pm_id] = {'name': pm_name, 'amount': 0.0}
                income_by_method[pm_id]['amount'] += payment.amount
                total_payments += payment.amount

        payment_rows = list(income_by_method.values())
        payment_rows.sort(key=lambda x: x['amount'], reverse=True)

        # 5. Item Wise Sales Details
        item_sales_map = {}
        for line in order_lines:
            prod = line.product_id
            pid = prod.id
            categ_name = prod.product_tmpl_id.pos_categ_ids[0].name if prod.product_tmpl_id.pos_categ_ids else (prod.categ_id.name or 'Uncategorized')
            base_product_name = prod.product_tmpl_id.name or prod.name
            price_unit = line.price_unit
            disc_amt = (line.price_unit * line.qty * (line.discount or 0.0) / 100.0)

            key = (categ_name, base_product_name, price_unit)
            if key not in item_sales_map:
                item_sales_map[key] = {
                    'group_name': categ_name,
                    'item_name': base_product_name,
                    'price': price_unit,
                    'qty': 0.0,
                    'time': 0.0,
                    'net': 0.0,
                    'order_tag': 0.0,
                    'grand': 0.0,
                }
            item_sales_map[key]['qty'] += line.qty
            item_sales_map[key]['net'] += line.price_subtotal
            item_sales_map[key]['order_tag'] += disc_amt
            item_sales_map[key]['grand'] += line.price_subtotal_incl

        item_details = list(item_sales_map.values())
        item_details.sort(key=lambda x: (x['group_name'].lower(), -x['qty'], x['item_name'].lower()))

        return {
            'work_period_str': work_period_str,
            'session_name': self.name,
            'dept_name': dept_name,
            'dept_sales_rows': dept_sales_rows,
            'info_rows': info_rows,
            'accounts_rows': accounts_rows,
            'payment_rows': payment_rows,
            'total_payments': total_payments,
            'item_details': item_details,
        }

    def _render_closing_summary_email_html(self, data):
        """Render responsive HTML email body with all 5 structured tables matching the reference design."""
        self.ensure_one()
        html = f"""
        <div style="font-family: Arial, Helvetica, sans-serif; font-size: 13px; color: #333333; line-height: 1.4; max-width: 900px; margin: 0 auto;">
            <div style="text-align: center; margin-bottom: 25px; padding: 12px 10px; background-color: #f8f9fa; border: 1px solid #e2e8f0; border-radius: 4px;">
                <h3 style="margin: 0; font-size: 15px; font-weight: bold; color: #1e293b;">
                    3S-ORDERLY generated Mail: {data['work_period_str']}
                </h3>
            </div>

            <!-- Table 1: Department Wise Sales -->
            <table style="width: 100%; max-width: 450px; border-collapse: collapse; margin-bottom: 25px; border: 1px solid #333333;">
                <thead>
                    <tr style="background-color: #f1f5f9; border-bottom: 1px solid #333333;">
                        <th style="padding: 7px 10px; text-align: left; font-weight: bold; border-right: 1px solid #333333;">Department Wise Sales</th>
                        <th style="padding: 7px 10px; text-align: right; font-weight: bold;">Value</th>
                    </tr>
                </thead>
                <tbody>
        """
        for d in data['dept_sales_rows']:
            html += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 6px 10px; border-right: 1px solid #333333;">{d['name']}</td>
                        <td style="padding: 6px 10px; text-align: right;">{d['value']:,.2f}</td>
                    </tr>
            """
        html += """
                </tbody>
            </table>

            <!-- Table 2: Information -->
            <table style="width: 100%; max-width: 450px; border-collapse: collapse; margin-bottom: 25px; border: 1px solid #333333;">
                <thead>
                    <tr style="background-color: #f1f5f9; border-bottom: 1px solid #333333;">
                        <th style="padding: 7px 10px; text-align: left; font-weight: bold; border-right: 1px solid #333333;">Information</th>
                        <th style="padding: 7px 10px; text-align: right; font-weight: bold;">Value</th>
                    </tr>
                </thead>
                <tbody>
        """
        for label, val in data['info_rows']:
            html += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 5px 10px; border-right: 1px solid #333333;">{label}</td>
                        <td style="padding: 5px 10px; text-align: right;">{val}</td>
                    </tr>
            """
        html += """
                </tbody>
            </table>

            <!-- Table 3: Accounts -->
            <table style="width: 100%; max-width: 450px; border-collapse: collapse; margin-bottom: 25px; border: 1px solid #333333;">
                <thead>
                    <tr style="background-color: #f1f5f9; border-bottom: 1px solid #333333;">
                        <th style="padding: 7px 10px; text-align: left; font-weight: bold; border-right: 1px solid #333333;">Accounts</th>
                        <th style="padding: 7px 10px; text-align: right; font-weight: bold;">Balance</th>
                    </tr>
                </thead>
                <tbody>
        """
        for acc_name, bal in data['accounts_rows']:
            html += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 5px 10px; border-right: 1px solid #333333;">{acc_name}</td>
                        <td style="padding: 5px 10px; text-align: right;">{bal}</td>
                    </tr>
            """
        html += """
                </tbody>
            </table>

            <!-- Table 4: Payment Accounts -->
            <table style="width: 100%; max-width: 450px; border-collapse: collapse; margin-bottom: 25px; border: 1px solid #333333;">
                <thead>
                    <tr style="background-color: #f1f5f9; border-bottom: 1px solid #333333;">
                        <th style="padding: 7px 10px; text-align: left; font-weight: bold; border-right: 1px solid #333333;">Payment Accounts</th>
                        <th style="padding: 7px 10px; text-align: right; font-weight: bold;">Balance</th>
                    </tr>
                </thead>
                <tbody>
        """
        for p in data['payment_rows']:
            html += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 5px 10px; border-right: 1px solid #333333;">{p['name']}</td>
                        <td style="padding: 5px 10px; text-align: right;">{p['amount']:,.2f}</td>
                    </tr>
            """
        html += f"""
                    <tr style="border-top: 1px solid #333333; font-weight: bold; background-color: #f8fafc;">
                        <td style="padding: 6px 10px; border-right: 1px solid #333333;">Total Payments</td>
                        <td style="padding: 6px 10px; text-align: right;">{data['total_payments']:,.2f}</td>
                    </tr>
                </tbody>
            </table>

            <!-- Table 5: Item Wise Sales Details -->
            <div style="margin-top: 30px; margin-bottom: 10px;">
                <h4 style="margin: 0 0 10px 0; font-size: 14px; font-weight: bold; color: #0f172a;">Item Wise Sales Details</h4>
                <table style="width: 100%; border-collapse: collapse; border: 1px solid #333333;">
                    <thead>
                        <tr style="background-color: #f1f5f9; border-bottom: 1px solid #333333;">
                            <th style="padding: 7px 8px; text-align: left; font-weight: bold; border-right: 1px solid #333333;">GroupName</th>
                            <th style="padding: 7px 8px; text-align: left; font-weight: bold; border-right: 1px solid #333333;">ItemName</th>
                            <th style="padding: 7px 8px; text-align: right; font-weight: bold; border-right: 1px solid #333333;">Price</th>
                            <th style="padding: 7px 8px; text-align: right; font-weight: bold; border-right: 1px solid #333333;">Quantity</th>
                            <th style="padding: 7px 8px; text-align: right; font-weight: bold; border-right: 1px solid #333333;">Time(m)</th>
                            <th style="padding: 7px 8px; text-align: right; font-weight: bold; border-right: 1px solid #333333;">Net</th>
                            <th style="padding: 7px 8px; text-align: right; font-weight: bold; border-right: 1px solid #333333;">Order Tag</th>
                            <th style="padding: 7px 8px; text-align: right; font-weight: bold;">Grand</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        for item in data['item_details']:
            html += f"""
                        <tr style="border-bottom: 1px solid #e2e8f0;">
                            <td style="padding: 5px 8px; border-right: 1px solid #333333;">{item['group_name']}</td>
                            <td style="padding: 5px 8px; border-right: 1px solid #333333;">{item['item_name']}</td>
                            <td style="padding: 5px 8px; text-align: right; border-right: 1px solid #333333;">{item['price']:,.2f}</td>
                            <td style="padding: 5px 8px; text-align: right; border-right: 1px solid #333333;">{item['qty']:.2f}</td>
                            <td style="padding: 5px 8px; text-align: right; border-right: 1px solid #333333;">{item['time']:.2f}</td>
                            <td style="padding: 5px 8px; text-align: right; border-right: 1px solid #333333;">{item['net']:,.2f}</td>
                            <td style="padding: 5px 8px; text-align: right; border-right: 1px solid #333333;">{item['order_tag']:,.2f}</td>
                            <td style="padding: 5px 8px; text-align: right;">{item['grand']:,.2f}</td>
                        </tr>
            """
        html += """
                    </tbody>
                </table>
            </div>

            <div style="margin-top: 30px; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 10px;">
                *** This is a computer-generated summary email and attached spreadsheet sent upon POS session closure.
            </div>
        </div>
        """
        return html

    def _generate_closing_summary_xlsx(self, data):
        """Generate organized Excel file (.xlsx) in memory containing Tables 1 through 5."""
        self.ensure_one()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Session Summary')

        title_format = workbook.add_format({'bold': True, 'font_size': 13, 'align': 'center'})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#E2E8F0', 'border': 1, 'font_size': 10})
        cell_format = workbook.add_format({'border': 1, 'font_size': 10})
        num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00', 'font_size': 10})
        bold_cell_format = workbook.add_format({'bold': True, 'border': 1, 'font_size': 10})
        bold_num_format = workbook.add_format({'bold': True, 'border': 1, 'num_format': '#,##0.00', 'font_size': 10})

        worksheet.set_column(0, 0, 24)
        worksheet.set_column(1, 1, 28)
        worksheet.set_column(2, 7, 16)

        # Title
        worksheet.merge_range(0, 0, 0, 7, f"3S-ORDERLY generated Mail: {data['work_period_str']}", title_format)

        # Table 1: Department Wise Sales
        row = 2
        worksheet.write(row, 0, "Department Wise Sales", header_format)
        worksheet.write(row, 1, "Value", header_format)
        row += 1
        for d in data['dept_sales_rows']:
            worksheet.write(row, 0, d['name'], cell_format)
            worksheet.write(row, 1, d['value'], num_format)
            row += 1

        # Table 2: Information
        row += 1
        worksheet.write(row, 0, "Information", header_format)
        worksheet.write(row, 1, "Value", header_format)
        row += 1
        for label, val in data['info_rows']:
            worksheet.write(row, 0, label, cell_format)
            worksheet.write(row, 1, val, cell_format)
            row += 1

        # Table 3: Accounts
        row += 1
        worksheet.write(row, 0, "Accounts", header_format)
        worksheet.write(row, 1, "Balance", header_format)
        row += 1
        for acc_name, bal in data['accounts_rows']:
            worksheet.write(row, 0, acc_name, cell_format)
            worksheet.write(row, 1, bal, cell_format)
            row += 1

        # Table 4: Payment Accounts
        row += 1
        worksheet.write(row, 0, "Payment Accounts", header_format)
        worksheet.write(row, 1, "Balance", header_format)
        row += 1
        for p in data['payment_rows']:
            worksheet.write(row, 0, p['name'], cell_format)
            worksheet.write(row, 1, p['amount'], num_format)
            row += 1
        worksheet.write(row, 0, "Total Payments", bold_cell_format)
        worksheet.write(row, 1, data['total_payments'], bold_num_format)
        row += 1

        # Table 5: Item Wise Sales Details
        row += 2
        worksheet.merge_range(row, 0, row, 7, "Item Wise Sales Details", workbook.add_format({'bold': True, 'font_size': 12}))
        row += 1
        item_headers = ["GroupName", "ItemName", "Price", "Quantity", "Time(m)", "Net", "Order Tag", "Grand"]
        for col, h in enumerate(item_headers):
            worksheet.write(row, col, h, header_format)
        row += 1

        for item in data['item_details']:
            worksheet.write(row, 0, item['group_name'], cell_format)
            worksheet.write(row, 1, item['item_name'], cell_format)
            worksheet.write(row, 2, item['price'], num_format)
            worksheet.write(row, 3, item['qty'], num_format)
            worksheet.write(row, 4, item['time'], num_format)
            worksheet.write(row, 5, item['net'], num_format)
            worksheet.write(row, 6, item['order_tag'], num_format)
            worksheet.write(row, 7, item['grand'], num_format)
            row += 1

        workbook.close()
        output.seek(0)
        return output.read()

    def _send_session_closing_summary_mail(self):
        """Compile report data and dispatch automated summary email with Excel attachment to POS Administrators."""
        self.ensure_one()
        recipients = self._get_pos_admin_recipients()
        if not recipients:
            _logger.warning("No active POS Administrator recipients found for session %s closing email.", self.name)
            return {'success': True, 'warning': 'No recipients configured'}

        try:
            data = self._get_closing_summary_data()
            html_body = self._render_closing_summary_email_html(data)
            xlsx_bytes = self._generate_closing_summary_xlsx(data)

            clean_name = self.name.replace('/', '_').replace(' ', '_')
            filename = f"Work_Period_Summary_{clean_name}.xlsx"

            attachment = self.env['ir.attachment'].sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(xlsx_bytes),
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'res_model': 'pos.session',
                'res_id': self.id,
            })

            date_str = fields.Date.context_today(self).strftime('%d %B %Y')
            subject = f"Work Period Sales Summary: {self.name} - {date_str}"

            mail = self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': html_body,
                'email_to': ', '.join(recipients),
                'attachment_ids': [(4, attachment.id)],
            })
            mail.send(raise_exception=True)
            _logger.info("Session closing summary email sent successfully for session %s to %s", self.name, recipients)
            return {'success': True}
        except Exception as e:
            _logger.error("Failed to send session closing summary email for session %s: %s", self.name, str(e))
            return {'success': False, 'error': str(e)}

    def close_session_from_ui(self, bank_payment_method_diff_pairs=None):
        """Hook into POS frontend session closing to dispatch email and report delivery status."""
        res = super().close_session_from_ui(bank_payment_method_diff_pairs=bank_payment_method_diff_pairs)
        if isinstance(res, dict) and res.get('successful'):
            mail_res = self._send_session_closing_summary_mail()
            res['mail_success'] = mail_res.get('success', False)
            res['mail_error'] = mail_res.get('error', '')
        return res
