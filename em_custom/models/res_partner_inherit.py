# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    has_security_cheque = fields.Boolean(string="Security Cheque")
    security_cheque_amount = fields.Monetary(
        string="Cheque Amount",
        currency_field='currency_id',
    )
    security_cheque_file = fields.Binary(string="Cheque File", attachment=True)
    security_cheque_filename = fields.Char(string="Cheque Filename")