# -*- coding: utf-8 -*-

from odoo import fields, models

class PaymentMethod(models.Model):
    """
    Inherit 'payment.method' to add a specific field for the SmilePay 'Pay_zg' code.
    This creates a clear link between the user-selected payment method in Odoo
    and the corresponding code required by the SmilePay API.
    """
    _inherit = 'payment.method'

    smilepay_payment_code = fields.Char(
        string='SmilePay Payment Code (Pay_zg)',
        help="The 'Pay_zg' code for the SmilePay API. \n"
             "For example: \n"
             " - '2' for Virtual Account/ATM \n"
             " - '3' for Convenience Store Bill \n"
             " - '4' for 7-11 iBon \n"
             " - '6' for FamiPort \n"
             " - '51' for C2C Cash on Delivery \n"
             " - '55' for B2C Cash on Delivery"
    )
