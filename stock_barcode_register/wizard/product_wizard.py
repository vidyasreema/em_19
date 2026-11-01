from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain


class StockBarcodeProductWizard(models.TransientModel):
    """Controlled product creation from a receipt line: duplicate products, zero cost
    and wrong units are among the causes of data pollution."""
    _name = 'stock.barcode.product.wizard'
    _description = 'New Product from Receipt'

    picking_id = fields.Many2one('stock.picking', required=True)
    name = fields.Char('Product Name', required=True)
    uom_id = fields.Many2one('uom.uom', 'Unit', required=True, default=lambda self: self.env.ref('uom.product_uom_kgm', raise_if_not_found=False))
    categ_id = fields.Many2one('product.category', 'Category', required=True)
    storage_type = fields.Selection([('fresh', 'Fresh'), ('chilled', 'Chilled'), ('frozen', 'Frozen')], required=True)
    standard_price = fields.Float('Cost (from vendor invoice)', required=True, digits='Product Price')
    default_code = fields.Char('Internal Reference')
    barcode = fields.Char('Product Code / Barcode', help="Product code read from the carton barcode, used for the duplicate check.")
    product_uom_qty = fields.Float('Quantity on Invoice', digits='Product Unit')
    duplicate_ids = fields.Many2many('product.product', compute='_compute_duplicate_ids', string='Possible Duplicates')
    confirm_not_duplicate = fields.Boolean("This is a new product, not one of the products above")

    @api.depends('name', 'default_code', 'barcode')
    def _compute_duplicate_ids(self):
        Product = self.env['product.product'].with_context(active_test=False)
        for wizard in self:
            domains = []
            if wizard.name:
                domains.append(Domain('name', '=ilike', wizard.name.strip()))
            if wizard.default_code:
                domains.append(Domain('default_code', '=ilike', wizard.default_code.strip()))
            if wizard.barcode:
                code = wizard.barcode.strip()
                domains.append(Domain('barcode', 'in', [code, code.lstrip('0')]) | Domain('default_code', '=', code))
            wizard.duplicate_ids = Product.search(Domain.OR(domains), limit=10) if domains else Product

    def _get_product_values(self):
        vals = {
            'name': self.name.strip(),
            'type': 'consu',
            'is_storable': True,
            'uom_id': self.uom_id.id,
            'categ_id': self.categ_id.id,
            'storage_type': self.storage_type,
            'standard_price': self.standard_price,
            'default_code': self.default_code or False,
            'barcode': self.barcode or False,
        }
        Template = self.env['product.template']
        if 'available_in_pos' in Template._fields:
            vals['available_in_pos'] = True
        manufacture = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
        if manufacture:
            vals['route_ids'] = [(4, manufacture.id)]
        return vals

    def action_create(self):
        self.ensure_one()
        if not self.env.user.has_group('stock_barcode_register.group_barcode_product_creator'):
            raise AccessError(_("Only the inventory and pricing officer can create products from a receipt."))
        if self.picking_id.state in ('done', 'cancel'):
            raise UserError(_("The receipt is already validated or cancelled."))
        if self.standard_price <= 0:
            raise UserError(_("Enter the cost from the vendor invoice."))
        if self.duplicate_ids and not self.confirm_not_duplicate:
            raise UserError(_("Possible duplicates found: %s. Check them, or confirm that this is a new product.",
                              ", ".join(self.duplicate_ids.mapped('display_name'))))
        product = self.env['product.product'].sudo().create(self._get_product_values())
        picking = self.picking_id
        self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': self.product_uom_qty,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': picking.company_id.id,
        })
        reviewers = picking.company_id.barcode_register_followup_user_ids or self.env.user
        for user in reviewers:
            product.product_tmpl_id.sudo().activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_("Review new product"),
                note=_("Created from receipt %s: complete the sale price and settings.", picking.name),
                user_id=user.id,
            )
        return {'type': 'ir.actions.act_window_close'}
