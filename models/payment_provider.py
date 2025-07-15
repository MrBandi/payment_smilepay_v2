# -*- coding: utf-8 -*-

import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from werkzeug.urls import url_join

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.addons.payment import utils as payment_utils

_logger = logging.getLogger('payment_smilepay_v2.provider')

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('smilepay', 'SmilePay')],
        ondelete={'smilepay': 'set default'}
    )
    
    # SmilePay specific fields
    smilepay_dcvc = fields.Char(
        string="商家代號 (Dcvc)",
        help="SmilePay 商家代號，請至商家後台確認",
        required_if_provider='smilepay'
    )
    smilepay_rvg2c = fields.Char(
        string="參數碼 (Rvg2c)",
        help="SmilePay 參數碼，請至商家後台確認",
        required_if_provider='smilepay'
    )
    smilepay_verify_key = fields.Char(
        string="檢查碼 (Verify_key)",
        help="SmilePay 檢查碼，請至商家後台確認",
        required_if_provider='smilepay'
    )
    smilepay_merchant_verify_param = fields.Char(
        string="商家驗證參數",
        help="用於驗證回調數據的商家驗證參數（4碼）"
    )
    smilepay_api_url = fields.Char(
        string="API URL",
        default="https://ssl.smse.com.tw/api/SPPayment.asp",
        help="SmilePay API 位置"
    )

    @api.model
    def _get_compatible_providers(self, *args, currency_id=None, **kwargs):
        """Override to ensure SmilePay is available for TWD currency."""
        providers = super()._get_compatible_providers(*args, currency_id=currency_id, **kwargs)
        currency = self.env['res.currency'].browse(currency_id) if currency_id else None
        
        if currency and currency.name == 'TWD':
            smilepay_providers = self.search([
                ('code', '=', 'smilepay'),
                ('state', 'in', ['enabled', 'test'])
            ])
            providers |= smilepay_providers
            
        return providers

    def _compute_feature_support_fields(self):
        """Compute the feature support fields based on the provider."""
        super()._compute_feature_support_fields()
        providers_smilepay = self.filtered(lambda p: p.code == 'smilepay')
        # Set SmilePay specific feature support
        for provider in providers_smilepay:
            provider.support_manual_capture = False
            provider.support_refund = 'partial'
            provider.support_tokenization = False
            provider.support_express_checkout = False

    def _should_build_inline_form(self, is_validation=False):
        """Return whether the inline form should be instantiated.
        
        SmilePay uses redirect flow, so we don't use inline forms.
        """
        if self.code != 'smilepay':
            return super()._should_build_inline_form(is_validation)
        # SmilePay 使用重定向流程，不使用內聯表單
        return False
    
    def _get_redirect_form_view(self, is_validation=False):
        """Return the view of the template used to render the redirect form."""
        if self.code == 'smilepay':
            # SmilePay 使用自定義重定向表單 - 返回視圖記錄而不是字符串
            try:
                return self.env.ref('payment_smilepay_v2.smilepay_redirect_form')
            except ValueError as e:
                _logger.error("SmilePay redirect form template not found: %s", e)
                # 如果找不到模板，使用預設的重定向表單
                return super()._get_redirect_form_view(is_validation)
        return super()._get_redirect_form_view(is_validation)

    def _get_default_payment_method_codes(self):
        """Return the default payment method codes."""
        default_codes = super()._get_default_payment_method_codes()
        if self.code == 'smilepay':
            return ['smilepay_atm', 'smilepay_cvs', 'smilepay_ibon', 'smilepay_fami']
        return default_codes

    def _smilepay_make_request(self, data):
        """Make a request to SmilePay API."""
        try:
            # Convert data to URL parameters
            params = urlencode(data, encoding='utf-8')
            url = f"{self.smilepay_api_url}?{params}"
            
            _logger.info("SmilePay API Request URL: %s", url)
            
            response = requests.get(url, timeout=60)
            _logger.info("SmilePay API Response Status: %s", response.status_code)
            _logger.info("SmilePay API Response Content: %s", response.content.decode('utf-8', errors='ignore'))
            
            response.raise_for_status()
            
            # Parse XML response
            try:
                root = ET.fromstring(response.content)
                result = self._parse_smilepay_response(root)
                _logger.info("SmilePay API Parsed Result: %s", result)
                return result
            except ET.ParseError as e:
                _logger.error("SmilePay XML Parse Error: %s", e)
                _logger.error("SmilePay Raw Response: %s", response.content.decode('utf-8', errors='ignore'))
                return {'error': True, 'message': 'Invalid XML response'}
                
        except requests.RequestException as e:
            _logger.error("SmilePay API Request Error: %s", e)
            return {'error': True, 'message': str(e)}

    def _parse_smilepay_response(self, xml_root):
        """Parse SmilePay XML response."""
        result = {}
        
        for element in xml_root:
            if element.tag == 'Status':
                result['status'] = element.text
            elif element.tag == 'Desc':
                result['desc'] = element.text
            elif element.tag == 'SmilePayNO':
                result['smilepay_no'] = element.text
            elif element.tag == 'Data_id':
                result['data_id'] = element.text
            elif element.tag == 'Amount':
                result['amount'] = element.text
            elif element.tag == 'PayEndDate':
                result['pay_end_date'] = element.text
            elif element.tag == 'AtmBankNo':
                result['atm_bank_no'] = element.text
            elif element.tag == 'AtmNo':
                result['atm_no'] = element.text
            elif element.tag == 'Barcode1':
                result['barcode1'] = element.text
            elif element.tag == 'Barcode2':
                result['barcode2'] = element.text
            elif element.tag == 'Barcode3':
                result['barcode3'] = element.text
            elif element.tag == 'IbonNo':
                result['ibon_no'] = element.text
            elif element.tag == 'FamiNO':
                result['fami_no'] = element.text
        
        return result

    def _get_supported_currencies(self):
        """Return supported currencies for SmilePay."""
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'smilepay':
            supported_currencies = supported_currencies.filtered(lambda c: c.name == 'TWD')
        return supported_currencies

    def _smilepay_get_api_url(self):
        """Get the API URL for the current environment."""
        return self.smilepay_api_url or "https://ssl.smse.com.tw/api/SPPayment.asp"

    @api.constrains('smilepay_dcvc', 'smilepay_rvg2c', 'smilepay_verify_key', 'state')
    def _check_smilepay_configuration(self):
        """Validate SmilePay configuration when enabling the provider."""
        for provider in self.filtered(lambda p: p.code == 'smilepay' and p.state == 'enabled'):
            if not all([provider.smilepay_dcvc, provider.smilepay_rvg2c, provider.smilepay_verify_key]):
                raise ValidationError(_(
                    "SmilePay requires Dcvc (商家代號), Rvg2c (參數碼), and Verify_key (檢查碼) to be configured before enabling."
                ))
