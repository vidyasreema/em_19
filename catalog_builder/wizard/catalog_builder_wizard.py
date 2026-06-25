# -*- coding: utf-8 -*-
from odoo import models, fields, api


class CatalogBuilderWizard(models.TransientModel):
    _name = 'catalog.builder.wizard'
    _description = 'Select Products for Catalog'

    catalog_id = fields.Many2one(
        'catalog.builder',
        string='Catalog',
        required=True,
    )
    category_id = fields.Many2one(
        'product.category',
        string='Filter by Category',
    )
    product_ids = fields.Many2many(
        'product.product',
        string='Available Products',
        compute='_compute_product_ids',
    )
    selected_product_ids = fields.Many2many(
        'product.product',
        'catalog_wizard_selected_rel',
        'wizard_id',
        'product_id',
        string='Selected Products',
    )

    @api.depends('category_id')
    def _compute_product_ids(self):
        for wizard in self:
            domain = [('sale_ok', '=', True)]
            if wizard.category_id:
                domain.append(('categ_id', '=', wizard.category_id.id))
            wizard.product_ids = self.env['product.product'].search(domain)

    def action_confirm(self):
        self.ensure_one()
        existing_product_ids = self.catalog_id.line_ids.mapped('product_id').ids
        lines_to_create = []
        for product in self.selected_product_ids:
            if product.id in existing_product_ids:
                continue
            lines_to_create.append({
                'catalog_id': self.catalog_id.id,
                'product_id': product.id,
                'name': product.display_name,
                'price': product.list_price,
                'image': product.image_1920,
                'description': product.description_sale or '',
            })
        if lines_to_create:
            self.env['catalog.line'].create(lines_to_create)
        return {'type': 'ir.actions.act_window_close'}