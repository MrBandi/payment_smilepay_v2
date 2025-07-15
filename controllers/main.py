# -*- coding: utf-8 -*-

import logging
import pprint

from odoo import http
from odoo.http import request
from odoo.addons.payment.controllers.post_processing import PaymentPostProcessing

_logger = logging.getLogger('payment_smilepay_v2.controller')

class SmilePayController(http.Controller):
    
    _return_url = '/payment/smilepay/return'
    _webhook_url = '/payment/smilepay/webhook'
    _process_url = '/payment/smilepay/process'

    @http.route('/payment/smilepay/process', type='http', auth='public', methods=['POST'], csrf=True, website=True)
    def smilepay_process_payment_method(self, **post):
        """Process SmilePay payment method selection."""
        _logger.info("SmilePay payment method selection with data:\n%s", pprint.pformat(post))
        
        try:
            reference = post.get('reference')
            payment_method = post.get('payment_method', '2')  # 預設 ATM
            
            _logger.info("SmilePay: Processing payment with method=%s for reference=%s", payment_method, reference)
            
            if not reference:
                return self._render_error('Missing reference')
            
            # 找到交易記錄
            tx_sudo = request.env['payment.transaction'].sudo().search([
                ('reference', '=', reference),
                ('provider_code', '=', 'smilepay')
            ], limit=1)
            
            if not tx_sudo:
                return self._render_error('Transaction not found')
            
            _logger.info("SmilePay: Found transaction %s, current payment method: %s", tx_sudo.reference, tx_sudo.smilepay_payment_method)
            
            # 強制設置付款方式，確保不會被默認值覆蓋
            tx_sudo.write({
                'smilepay_payment_method': payment_method
            })
            
            # 驗證付款方式確實已更新 - 使用 Odoo 17 的正確方法
            tx_sudo.invalidate_recordset()
            _logger.info("SmilePay: Updated payment method to %s, verifying: %s", payment_method, tx_sudo.smilepay_payment_method)
            
            # 執行 SmilePay 背景取號
            success = tx_sudo._smilepay_process_background_payment()
            
            if not success:
                return self._render_error('Payment processing failed. Please try again.')
            
            # 重定向到付款狀態頁面
            return request.redirect(f'/payment/smilepay/status/{tx_sudo.reference}')
            
        except Exception as e:
            _logger.exception("Error processing SmilePay payment method selection: %s", e)
            return self._render_error(f'Payment processing failed: {str(e)}')

    def _render_error(self, error_message):
        """Render error page with proper context"""
        try:
            return request.render('payment_smilepay_v2.smilepay_payment_error', {
                'error_message': error_message,
                'website': request.website,
                'main_object': request.website,
            })
        except Exception as e:
            _logger.error("Failed to render error template: %s", e)
            # 如果模板渲染失敗，返回簡單的 HTML 錯誤頁面
            return request.make_response(f'''
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Payment Error</title>
                    <meta charset="utf-8">
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 40px; }}
                        .error {{ background: #f8d7da; color: #721c24; padding: 20px; border-radius: 5px; }}
                    </style>
                </head>
                <body>
                    <div class="error">
                        <h2>SmilePay Payment Error</h2>
                        <p>{error_message}</p>
                        <p><a href="/shop">Return to Shop</a></p>
                    </div>
                </body>
                </html>
            ''', status=500, headers={'Content-Type': 'text/html'})

    @http.route(_return_url, type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def smilepay_return(self, **post):
        """Handle return from SmilePay after payment."""
        _logger.info("SmilePay return with data:\n%s", pprint.pformat(post))
        
        # Process the notification
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                'smilepay', post
            )
            tx_sudo._process_notification_data(post)
        except Exception as e:
            _logger.exception("Error processing SmilePay return: %s", e)
            return self._render_error('Payment processing failed. Please contact support.')

        # Redirect to payment processing page
        return PaymentPostProcessing().payment_status_page(tx_sudo.reference)

    @http.route(_webhook_url, type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def smilepay_webhook(self, **post):
        """Handle webhook notifications from SmilePay."""
        _logger.info("SmilePay webhook with data:\n%s", pprint.pformat(post))
        
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                'smilepay', post
            )
            tx_sudo._process_notification_data(post)
            
            # Return the expected response for SmilePay
            roturl_status = post.get('Roturl_status', 'RL_OK')
            return f"<Roturlstatus>{roturl_status}</Roturlstatus>"
            
        except Exception as e:
            _logger.exception("Error processing SmilePay webhook: %s", e)
            return "ERROR"

    @http.route('/payment/smilepay/status/<string:reference>', type='http', auth='public', methods=['GET'], website=True)
    def smilepay_payment_status(self, reference, **kwargs):
        """Display SmilePay payment status for a transaction."""
        try:
            tx_sudo = request.env['payment.transaction'].sudo().search([
                ('reference', '=', reference),
                ('provider_code', '=', 'smilepay')
            ], limit=1)
            
            if not tx_sudo:
                return request.not_found()
            
            # Render our custom status template
            payment_info_dict = tx_sudo.get_smilepay_payment_info_dict()
            
            return request.render('payment_smilepay_v2.smilepay_payment_status', {
                'tx': tx_sudo,
                'payment_info': payment_info_dict,
                'page_name': 'payment_status',
                'website': request.website,
                'main_object': request.website,
            })
        except Exception as e:
            _logger.exception("Error rendering SmilePay payment status: %s", e)
            return self._render_error(f'Unable to display payment status: {str(e)}')
