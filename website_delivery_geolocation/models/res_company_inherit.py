from odoo import fields,models,api

class ResCompany(models.Model):
    _inherit = "res.company"

    shop_latitude = fields.Float(string="Shop Latitude")
    shop_longitude = fields.Float(string="Shop Longitude")