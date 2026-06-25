# -*- coding: utf-8 -*-
import base64
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CatalogBuilder(models.Model):
    _name = 'catalog.builder'
    _description = 'Product Catalog'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Catalog Number', required=True, copy=False,
        readonly=True, default=lambda self: 'New',
    )
    date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Printed')],
        string='Status', default='draft', required=True,
    )
    template = fields.Selection(
        [('the_cut', 'The Cut — Premium')],
        string='Template', default='the_cut', required=True,
    )
    customer_id = fields.Many2one(
        'res.partner', string='Customer (for pricelist only)',
    )
    line_ids = fields.One2many(
        'catalog.line', 'catalog_id', string='Catalog Lines',
    )
    pdf_file = fields.Binary(string='Generated PDF', readonly=True, copy=False)
    pdf_filename = fields.Char(string='PDF Filename', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('catalog.builder') or 'New'
        return super().create(vals_list)

    def action_open_product_picker(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Select Products',
            'res_model': 'catalog.builder.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_catalog_id': self.id},
        }

    def action_preview(self):
        """On-demand preview (FR-7 / BR-8): open the PDF in the browser viewer, no download, no save."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Please add at least one product first."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/pdf/catalog_builder.action_report_catalog/%s' % self.id,
            'target': 'new',  # opens in a new browser tab using the built-in PDF viewer
        }

    def action_print_save(self):
        """Print & Save (FR-8 / BR-4): generate PDF + save record + attach PDF, in one action."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Please add at least one product before printing."))
        pdf_content, _ct = self.env['ir.actions.report']._render_qweb_pdf(
            'catalog_builder.action_report_catalog', res_ids=self.ids)
        filename = '%s.pdf' % (self.name or 'Catalog')
        self.write({
            'pdf_file': base64.b64encode(pdf_content),
            'pdf_filename': filename,
            'state': 'done',
        })
        self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }


class CatalogLine(models.Model):
    _name = 'catalog.line'
    _description = 'Catalog Line'
    _order = 'sequence, id'

    catalog_id = fields.Many2one(
        'catalog.builder', string='Catalog', required=True, ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', string='Source Product', required=True, ondelete='restrict',
    )
    name = fields.Char(string='Display Name', required=True)
    price = fields.Float(string='Display Price')
    image = fields.Binary(string='Display Image')
    description = fields.Char(string='Description')
    origin = fields.Char(string='Origin')
    is_modified = fields.Boolean(string='Modified', default=False, readonly=True)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.price = self.product_id.list_price
            self.image = self.product_id.image_1920
            self.description = self.product_id.description_sale or ''

    def write(self, vals):
        tracked_fields = {'name', 'price', 'image', 'description', 'origin'}
        if tracked_fields.intersection(vals.keys()):
            vals['is_modified'] = True
        return super().write(vals)