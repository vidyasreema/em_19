# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = "product.category"

    catalog_image = fields.Binary(string="Catalog Section Image",
                                   help="Hero image shown on this animal's "
                                        "divider page in the catalog.")