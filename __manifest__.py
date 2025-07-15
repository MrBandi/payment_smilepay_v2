# -*- coding: utf-8 -*-
{
    'name': 'Payment SmilePay V2',
    'version': '17.0.1.3.0',
    'category': 'Accounting/Payment Providers',
    'summary': 'SmilePay payment provider integration for Taiwan market',
    'description': """
SmilePay Payment Provider
=========================

This module adds SmilePay as a payment provider in Odoo.

SmilePay supports multiple payment methods:
- Virtual ATM Account (虛擬帳號)
- Convenience Store Bills (超商帳單)
- 7-11 ibon
- FamiPort
- Cash on Delivery (貨到付款)
- Store pickup (超商取貨)

Key Features:
- Background payment code generation (背景取號)
- Multiple payment methods support
- Webhook integration for payment status updates
- Secure payment verification
- Taiwan market focused
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['payment', 'website', 'website_sale', 'sale'],
    'data': [
        'views/payment_provider_views.xml',
        'views/payment_transaction_views.xml',
        'templates/payment_redirect_form.xml',
        'templates/payment_confirmation.xml',
        'templates/payment_error.xml',
        'templates/payment_status.xml',
        'templates/portal_order_smilepay.xml',
        'data/payment_provider_data.xml',
        'data/payment_method_data.xml',
    ],
    'assets': {
        'website.assets_frontend': [
            'payment_smilepay_v2/static/src/css/payment_form.css',
            'payment_smilepay_v2/static/src/css/payment_status.css',
        ],
    },
    # 'images': ['static/src/img/smilepay_icon.png'],  # Commented out until actual icon is available
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
