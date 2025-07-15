# -*- coding: utf-8 -*-

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from werkzeug.urls import url_join
import ast

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.addons.payment import utils as payment_utils

_logger = logging.getLogger('payment_smilepay_v2.transaction')

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # SmilePay specific fields
    smilepay_payment_method = fields.Selection([
        ('2', '虛擬帳號/ATM'),
        ('3', '超商帳單'),
        ('4', '7-11 ibon'),
        ('6', 'FamiPort'),
        ('51', 'C2C 取貨付款'),
        ('52', 'C2C 純取貨'),
        ('55', 'B2C 取貨付款'),
        ('56', 'B2C 純取貨'),
        ('81', '黑貓貨到收現'),
        ('82', '黑貓宅配'),
        ('83', '黑貓逆物流'),
    ], string="SmilePay 付款方式")
    
    smilepay_payment_subtype = fields.Selection([
        ('7NET', '統一超商'),
        ('TCAT', '黑貓'),
        ('FAMI', '全家'),
    ], string="物流公司", default='7NET')
    
    smilepay_tracking_no = fields.Char(string="SmilePay 追蹤碼")
    smilepay_payment_no = fields.Char(string="繳費代碼")
    smilepay_atm_bank_no = fields.Char(string="銀行代號")
    smilepay_atm_no = fields.Char(string="虛擬帳號")
    smilepay_barcode1 = fields.Char(string="條碼1")
    smilepay_barcode2 = fields.Char(string="條碼2")
    smilepay_barcode3 = fields.Char(string="條碼3")
    smilepay_ibon_no = fields.Char(string="ibon 繳費代碼")
    smilepay_fami_no = fields.Char(string="全家繳費代碼")
    smilepay_pay_end_date = fields.Datetime(string="繳費期限")
    smilepay_payment_info = fields.Text(string="SmilePay 付款資訊 (JSON)", help="結構化的付款資訊數據")

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override to automatically set the smilepay_payment_method from the payment_method record.
        This ensures the user's choice is correctly passed to the transaction.
        """
        for vals in vals_list:
            # Check if the transaction is for SmilePay and has a payment_method_id
            if 'provider_id' in vals and 'payment_method_id' in vals:
                provider = self.env['payment.provider'].browse(vals.get('provider_id'))
                if provider.code == 'smilepay':
                    payment_method = self.env['payment.method'].browse(vals.get('payment_method_id'))
                    # If the payment method has a specific smilepay code, use it.
                    # This links the user's selection to the transaction data.
                    if hasattr(payment_method, 'smilepay_payment_code') and payment_method.smilepay_payment_code:
                        vals['smilepay_payment_method'] = payment_method.smilepay_payment_code
                        _logger.info("SmilePay: Auto-set payment method %s from payment_method_id %s for transaction %s", 
                                   payment_method.smilepay_payment_code, payment_method.id, vals.get('reference', 'unknown'))
        
        return super().create(vals_list)
    
    def _get_specific_rendering_values(self, processing_values):
        """Override to handle SmilePay redirect form rendering."""
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'smilepay':
            return res

        base_url = self.provider_id.get_base_url()
        
        # Ensure payment method is set
        if not self.smilepay_payment_method:
            _logger.warning("SmilePay rendering values failed for tx %s: Payment method not set.", self.reference)
            raise ValidationError(_("SmilePay Error: Payment method was not selected or passed correctly."))

        form_values = {
            'reference': self.reference,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_id.id,
            'provider_id': self.provider_id.id,
            'tx_url': f"{base_url}payment/smilepay/process",
            'return_url': f"{base_url}payment/smilepay/return",
            'smilepay_dcvc': self.provider_id.smilepay_dcvc,
            'smilepay_rvg2c': self.provider_id.smilepay_rvg2c,
            'smilepay_verify_key': self.provider_id.smilepay_verify_key,
            # MODIFIED: Removed the `or '2'` fallback to ensure correctness
            'smilepay_payment_method': self.smilepay_payment_method,
            'smilepay_payment_subtype': self.smilepay_payment_subtype or '7NET',
        }
        
        if self.partner_id:
            form_values.update({
                'partner_name': self.partner_id.name[:50] if self.partner_id.name else '',
                'partner_email': self.partner_id.email[:50] if self.partner_id.email else '',
                'partner_phone': self.partner_id.phone[:20] if self.partner_id.phone else '',
                'partner_mobile': self.partner_id.mobile[:20] if self.partner_id.mobile else '',
            })
        
        return form_values

    def _smilepay_process_background_payment(self):
        """處理 SmilePay 背景取號"""
        if self.provider_code != 'smilepay':
            return False
        
        # MODIFIED: Add a check to ensure the payment method is set before proceeding
        if not self.smilepay_payment_method:
            _logger.error("SmilePay background payment failed for tx %s: Payment method not set.", self.reference)
            self._set_error(_("SmilePay Error: Payment method was not selected or passed correctly."))
            return False
            
        try:
            provider = self.provider_id
            
            # 計算繳費截止日期（考慮台灣時區，設為3天後以確保安全）
            # 使用 UTC+8 台灣時區
            tw_tz = timezone(timedelta(hours=8))
            now_tw = datetime.now(tw_tz)
            deadline_dt = now_tw + timedelta(days=3)  # 改為3天後，更保険
            
            payload = {
                'Dcvc': provider.smilepay_dcvc,
                'Rvg2c': provider.smilepay_rvg2c,
                'Verify_key': provider.smilepay_verify_key,
                'Pay_zg': self.smilepay_payment_method,
                'Pay_subzg': self.smilepay_payment_subtype or '7NET',
                'Data_id': self.reference,
                'Amount': int(self.amount),
                'Pur_name': self._get_customer_name(),
                'Tel_number': self._get_customer_phone(),
                'Mobile_number': self._get_customer_mobile(),
                'Address': self._get_customer_address(),
                'Email': self._get_customer_email(),
                'Od_sob': self._get_order_description(),
                'Deadline_date': f"{deadline_dt.year}/{deadline_dt.month}/{deadline_dt.day}",  # SmilePay 日期格式，不補零
                'Deadline_time': '23:59:59',
                'Remark': self._get_order_remark(),
                'Roturl': self._get_roturl(),
                'Roturl_status': 'RL_OK',
            }
            
            _logger.info("SmilePay API payload: %s", payload)
            
            api_response = provider._smilepay_make_request(payload)
            
            if api_response.get('error'):
                self._set_error(f"SmilePay API Error: {api_response.get('message', 'Unknown error')}")
                return False
            
            if api_response.get('status') != '1':
                error_message = api_response.get('desc', 'Unknown error')
                self._set_error(f"SmilePay Payment Creation Failed: {error_message}")
                return False
            
            self._smilepay_store_payment_data(api_response)
            
            self.write({'state': 'pending'})
            
            self._confirm_sale_order()
            
            self._format_payment_info(api_response)
            
            _logger.info("SmilePay background payment processing completed for transaction %s", self.reference)
            return True
            
        except Exception as e:
            _logger.error("SmilePay background processing error: %s", str(e), exc_info=True)
            self._set_error(f"Payment processing failed: {str(e)}")
            return False

    def _get_roturl(self):
        """Get the return URL for SmilePay notifications."""
        provider = self.provider_id
        if isinstance(provider, (int, str)):
            provider = self.env['payment.provider'].browse(int(provider))
        
        base_url = provider.get_base_url().rstrip('/')
        return f"{base_url}/payment/smilepay/return"
    
    def _format_payment_info(self, api_response):
        """Format payment information for display as structured data."""
        payment_method = self.smilepay_payment_method
        
        payment_info = {
            'tracking_no': api_response.get('smilepay_no', ''),
            'order_no': self.reference,
            'amount': self.amount,
            'payment_method': payment_method,
            'pay_end_date': api_response.get('pay_end_date'),
        }
        
        if payment_method == '2':
            payment_info.update({
                'method_name': '虛擬帳號/ATM',
                'method_icon': 'fa-university',
                'method_color': 'primary',
                'bank_code': api_response.get('atm_bank_no', ''),
                'account_number': api_response.get('atm_no', ''),
                'instructions': '請使用 ATM 或網路銀行轉帳至上述帳號'
            })
        elif payment_method == '3':
            payment_info.update({
                'method_name': '超商帳單繳費',
                'method_icon': 'fa-store',
                'method_color': 'success',
                'barcode1': api_response.get('barcode1', ''),
                'barcode2': api_response.get('barcode2', ''),
                'barcode3': api_response.get('barcode3', ''),
                'instructions': '請至便利商店出示條碼繳費'
            })
        elif payment_method == '4':
            payment_info.update({
                'method_name': '7-11 ibon',
                'method_icon': 'fa-receipt',
                'method_color': 'warning',
                'payment_code': api_response.get('ibon_no', ''),
                'instructions': '請至 7-11 使用 ibon 機台繳費'
            })
        elif payment_method == '6':
            payment_info.update({
                'method_name': 'FamiPort (全家)',
                'method_icon': 'fa-credit-card',
                'method_color': 'info',
                'payment_code': api_response.get('fami_no', ''),
                'instructions': '請至全家便利商店使用 FamiPort 機台繳費'
            })
        
        self.write({
            'smilepay_payment_info': str(payment_info)
        })
        
        info_lines = []
        info_lines.append(f"追蹤碼: {payment_info.get('tracking_no','')}")
        info_lines.append(f"訂單號碼: {payment_info.get('order_no','')}")
        info_lines.append(f"金額: NT$ {payment_info.get('amount','')}")
        
        if payment_method == '2':
            info_lines.append(f"銀行代碼: {payment_info.get('bank_code','')}")
            info_lines.append(f"虛擬帳號: {payment_info.get('account_number','')}")
            info_lines.append(payment_info.get('instructions',''))
        elif payment_method == '3':
            info_lines.append(f"條碼1: {payment_info.get('barcode1','')}")
            info_lines.append(f"條碼2: {payment_info.get('barcode2','')}")
            info_lines.append(f"條碼3: {payment_info.get('barcode3','')}")
            info_lines.append(payment_info.get('instructions',''))
        elif payment_method in ['4', '6']:
            info_lines.append(f"{payment_info.get('method_name','')} 繳費代碼: {payment_info.get('payment_code','')}")
            info_lines.append(payment_info.get('instructions',''))
        
        if payment_info.get('pay_end_date'):
            info_lines.append(f"繳費期限: {payment_info['pay_end_date']}")
        
        return "\n".join(info_lines)

    def get_smilepay_payment_info_dict(self):
        """獲取解析後的 SmilePay 付款資訊字典"""
        if not self.smilepay_payment_info:
            return {}
        try:
            return ast.literal_eval(self.smilepay_payment_info)
        except (ValueError, SyntaxError) as e:
            _logger.warning("Failed to parse SmilePay payment info for transaction %s: %s", self.reference, e)
            return {}

    def _smilepay_store_payment_data(self, api_response):
        """Store SmilePay API response data."""
        vals = {
            'smilepay_tracking_no': api_response.get('smilepay_no'),
        }
        
        if api_response.get('pay_end_date'):
            try:
                vals['smilepay_pay_end_date'] = datetime.strptime(
                    api_response['pay_end_date'], '%Y/%m/%d %H:%M:%S'
                )
            except ValueError:
                pass
        
        if api_response.get('atm_bank_no'):
            vals['smilepay_atm_bank_no'] = api_response['atm_bank_no']
        if api_response.get('atm_no'):
            vals['smilepay_atm_no'] = api_response['atm_no']
        if api_response.get('barcode1'):
            vals['smilepay_barcode1'] = api_response['barcode1']
        if api_response.get('barcode2'):
            vals['smilepay_barcode2'] = api_response['barcode2']
        if api_response.get('barcode3'):
            vals['smilepay_barcode3'] = api_response['barcode3']
        if api_response.get('ibon_no'):
            vals['smilepay_ibon_no'] = api_response['ibon_no']
        if api_response.get('fami_no'):
            vals['smilepay_fami_no'] = api_response['fami_no']
        
        self.write(vals)

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """Override to find transaction from SmilePay notification data."""
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'smilepay' or len(tx) == 1:
            return tx

        reference = notification_data.get('Data_id')
        if not reference:
            raise ValidationError("SmilePay: Missing Data_id in notification data")

        tx = self.search([('reference', '=', reference), ('provider_code', '=', 'smilepay')])
        if not tx:
            raise ValidationError(f"SmilePay: No transaction found with reference {reference}")

        return tx

    def _process_notification_data(self, notification_data):
        """Process SmilePay notification data."""
        super()._process_notification_data(notification_data)
        if self.provider_code != 'smilepay':
            return

        if not self._smilepay_verify_notification(notification_data):
            _logger.warning(
                "SmilePay notification verification failed for transaction %s", self.reference
            )
            self._set_error("SmilePay: Invalid notification signature")
            return

        response_id = notification_data.get('Response_id')
        if response_id == '1':
            self._set_done()
            self.smilepay_payment_no = notification_data.get('Payment_no')
        elif response_id == '0':
            error_desc = notification_data.get('Errdesc', 'Payment failed')
            self._set_error(f"SmilePay: {error_desc}")
        else:
            self._set_pending()

    def _smilepay_verify_notification(self, notification_data):
        """Verify SmilePay notification using merchant verification parameter."""
        provider = self.provider_id
        if isinstance(provider, (int, str)):
            provider = self.env['payment.provider'].browse(int(provider))
        
        if not provider.smilepay_merchant_verify_param:
            # If no verification parameter is set, skip verification
            return True

        mid_smilepay = notification_data.get('Mid_smilepay')
        if not mid_smilepay:
            return False

        # Calculate verification code
        calculated_code = self._calculate_smilepay_verification_code(notification_data)
        
        return str(calculated_code) == str(mid_smilepay)

    def _calculate_smilepay_verification_code(self, notification_data):
        """Calculate SmilePay verification code."""
        provider = self.provider_id
        if isinstance(provider, (int, str)):
            provider = self.env['payment.provider'].browse(int(provider))
        
        # A = 商家驗證參數 (4位，不足補零)
        verify_param = provider.smilepay_merchant_verify_param or "0000"
        A = verify_param.zfill(4)
        
        # B = 收款金額 (8位，不足補零)
        amount = int(float(notification_data.get('Amount', '0')))
        B = str(amount).zfill(8)
        
        # C = Smseid 後四碼，非數字以9替代
        smseid = notification_data.get('Smseid', '0000')
        last_four = smseid[-4:] if len(smseid) >= 4 else smseid.zfill(4)
        C = ''.join('9' if not char.isdigit() else char for char in last_four)
        
        # D = A + B + C
        D = A + B + C
        
        # E = 取D的奇數位相加乘以9
        odd_sum = sum(int(D[i]) for i in range(0, len(D), 2))
        E = odd_sum * 9
        
        # F = 取D的偶數位相加乘以3
        even_sum = sum(int(D[i]) for i in range(1, len(D), 2))
        F = even_sum * 3
        
        return E + F

    def _get_order_description(self):
        """Get order description with product names for SmilePay Od_sob parameter."""
        try:
            if hasattr(self, 'sale_order_ids') and self.sale_order_ids:
                orders = self.sale_order_ids
                if orders and len(orders) > 0:
                    first_order = orders[0]
                    # 獲取訂單中的商品名稱
                    product_names = []
                    for line in first_order.order_line:
                        if line.product_id:
                            # 只取前30個字符避免超過SmilePay限制
                            print(line.product_id.name)
                            product_name = line.product_id.name[:30] if line.product_id.name else ''
                            if product_name and product_name not in product_names:
                                product_names.append(product_name)
                    
                    if product_names:
                        # 合併商品名稱，限制在50字符內（SmilePay限制）
                        description = ', '.join(product_names)
                        return description[:50] if description else f"Order {first_order.name}"
                    else:
                        return f"Order {first_order.name}"
        except Exception as e:
            _logger.warning("Error getting order description: %s", e)
        
        return f"Payment {self.reference}"
    
    def _get_order_remark(self):
        """Get order remark with product-specific notes for SmilePay Remark parameter."""
        remark_parts = []
        
        try:
            # 基本訂單資訊
            remark_parts.append(f"Order: {self.reference}")
            
            if hasattr(self, 'sale_order_ids') and self.sale_order_ids:
                orders = self.sale_order_ids
                if orders and len(orders) > 0:
                    first_order = orders[0]
                    
                    # 收集商品的詳細備註資訊（不包含商品名稱）
                    product_remarks = []
                    for line in first_order.order_line:
                        if line.product_id:
                            # 從訂單行描述提取商品的額外資訊
                            if hasattr(line, 'name') and line.name:
                                full_desc = line.name
                                product_name = line.product_id.name or ''
                                
                                # 如果描述比商品名稱長，提取額外的備註資訊
                                if len(full_desc) > len(product_name):
                                    # 清理 HTML 標籤和格式
                                    import re
                                    clean_desc = re.sub(r'<[^>]+>', '', full_desc)  # 移除 HTML 標籤
                                    clean_desc = re.sub(r'\n+', ' ', clean_desc)   # 替換換行符
                                    clean_desc = ' '.join(clean_desc.split())      # 清理多餘空格
                                    
                                    # 查找商品名稱之後的額外資訊
                                    if product_name in clean_desc:
                                        # 提取商品名稱後的所有內容
                                        extra_info = clean_desc.split(product_name, 1)
                                        if len(extra_info) > 1:
                                            extra_content = extra_info[1].strip()
                                            # 移除可能的前導符號 (:, -, 等)
                                            extra_content = re.sub(r'^[:\-\s]+', '', extra_content)
                                            
                                            if extra_content and len(extra_content) > 3:
                                                # 移除括號內的內容（如變體資訊）
                                                extra_content = re.sub(r'\([^)]*\)', '', extra_content).strip()
                                                
                                                # 再次檢查長度，移除括號後可能變太短
                                                if extra_content and len(extra_content) > 3:
                                                    # 處理多層冒號嵌套，只取最後的實際內容
                                                    if ':' in extra_content:
                                                        # 分割所有冒號，取最後一個非空的部分
                                                        parts = [part.strip() for part in extra_content.split(':')]
                                                        # 過濾掉空的部分，取最後一個有內容的部分
                                                        non_empty_parts = [part for part in parts if part]
                                                        if non_empty_parts:
                                                            final_content = non_empty_parts[-1]  # 取最後一個部分
                                                            if final_content and len(final_content) > 2:
                                                                product_remarks.append(final_content[:60])
                                                    else:
                                                        # 如果沒有冒號，直接使用額外內容
                                                        product_remarks.append(extra_content[:60])
                            
                            # 如果有商品的銷售描述，也加入（不包含商品名稱）
                            elif hasattr(line.product_id, 'description_sale') and line.product_id.description_sale:
                                clean_desc = ' '.join(line.product_id.description_sale.strip().split())
                                if clean_desc:
                                    product_remarks.append(clean_desc[:60])  # 直接使用描述，不加商品名稱
                    
                    # 添加商品備註（最多前2個商品的備註）
                    if product_remarks:
                        remark_parts.extend(product_remarks[:2])
            
            # 合併所有備註部分，限制在100字符內（SmilePay限制）
            full_remark = ' | '.join(remark_parts)
            return full_remark[:100] if full_remark else f"Order: {self.reference}"
            
        except Exception as e:
            _logger.warning("Error getting order remark: %s", e)
            return f"Order: {self.reference}"

    def _get_customer_name(self):
        """Get customer name."""
        try:
            partner = self.partner_id
            if isinstance(partner, (int, str)):
                partner = self.env['res.partner'].browse(int(partner))
            
            return partner.name[:50] if partner and partner.name else 'Customer'
        except Exception:
            return 'Customer'

    def _get_customer_phone(self):
        """Get customer phone."""
        try:
            partner = self.partner_id
            if isinstance(partner, (int, str)):
                partner = self.env['res.partner'].browse(int(partner))
            
            return partner.phone[:20] if partner and partner.phone else ''
        except Exception:
            return ''

    def _get_customer_mobile(self):
        """Get customer mobile."""
        try:
            partner = self.partner_id
            if isinstance(partner, (int, str)):
                partner = self.env['res.partner'].browse(int(partner))
            
            return partner.mobile[:20] if partner and partner.mobile else ''
        except Exception:
            return ''

    def _get_customer_address(self):
        """Get customer address."""
        try:
            partner = self.partner_id
            if isinstance(partner, (int, str)):
                partner = self.env['res.partner'].browse(int(partner))
            
            if partner:
                address_parts = [
                    partner.street,
                    partner.street2,
                    partner.city,
                    partner.state_id.name if partner.state_id else '',
                    partner.country_id.name if partner.country_id else ''
                ]
                address = ', '.join(filter(None, address_parts))
                return address[:100]
        except Exception:
            pass
        return ''

    def _get_customer_email(self):
        """Get customer email."""
        try:
            partner = self.partner_id
            if isinstance(partner, (int, str)):
                partner = self.env['res.partner'].browse(int(partner))
            
            return partner.email[:50] if partner and partner.email else ''
        except Exception:
            return ''

    def _get_invoice_name(self):
        """Get invoice name."""
        try:
            partner = self.partner_id
            if isinstance(partner, (int, str)):
                partner = self.env['res.partner'].browse(int(partner))
            
            return partner.name[:50] if partner and partner.name else ''
        except Exception:
            return ''

    def _confirm_sale_order(self):
        """確認與此付款交易關聯的銷售訂單"""
        try:
            if hasattr(self, 'sale_order_ids') and self.sale_order_ids:
                for order in self.sale_order_ids:
                    if order.state == 'draft':
                        _logger.info("Confirming sale order %s for SmilePay transaction %s", order.name, self.reference)
                        order.action_confirm()
                        _logger.info("Sale order %s confirmed successfully", order.name)
                    else:
                        _logger.info("Sale order %s already in state %s, no confirmation needed", order.name, order.state)
            else:
                # 如果沒有直接關聯，嘗試通過 reference 查找
                orders = self.env['sale.order'].search([('name', '=', self.reference)])
                if orders:
                    for order in orders:
                        if order.state == 'draft':
                            _logger.info("Confirming sale order %s found by reference %s", order.name, self.reference)
                            order.action_confirm()
                            _logger.info("Sale order %s confirmed successfully", order.name)
                else:
                    _logger.warning("No sale order found for SmilePay transaction %s", self.reference)
                    
        except Exception as e:
            _logger.error("Error confirming sale order for transaction %s: %s", self.reference, e)
            # 不要因為訂單確認失敗而影響付款流程
            pass
