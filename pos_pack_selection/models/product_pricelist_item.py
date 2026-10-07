from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    pack_uom_id = fields.Many2one(
        'uom.uom',
        string='Pack',
        domain="[('id', 'in', product_pack_uom_ids)]",
        help="If set, this rule only applies when the product is sold as this pack "
             "in the POS (Pack Size button or pack barcode). "
             "The price is the price of the whole pack.",
    )
    product_pack_uom_ids = fields.Many2many(
        related='product_tmpl_id.uom_ids',
        string='Product Packagings',
    )

    @api.model
    def default_get(self, fields_list):
        """In the Pack Prices screens, new rows default to the POS default pricelist."""
        res = super().default_get(fields_list)
        if self.env.context.get('pack_price_mode') and 'pricelist_id' in fields_list:
            config = self.env['pos.config'].search(
                [('company_id', '=', self.env.company.id), ('pricelist_id', '!=', False)],
                limit=1,
            )
            if config:
                res['pricelist_id'] = config.pricelist_id.id
        return res

    @api.constrains('pack_uom_id', 'product_tmpl_id', 'fixed_price')
    def _check_pack_rule(self):
        for rule in self.filtered('pack_uom_id'):
            if not rule.product_tmpl_id:
                raise ValidationError("A pack price must be set for a product.")
            if rule.pack_uom_id not in rule.product_tmpl_id.uom_ids:
                raise ValidationError(
                    f"'{rule.pack_uom_id.name}' is not a packaging of "
                    f"'{rule.product_tmpl_id.display_name}'. "
                    "Add it in the product's Sales tab > Packagings first."
                )
            if rule.fixed_price <= 0:
                raise ValidationError("The pack price must be greater than zero.")

    def _is_applicable_for(self, product, qty_in_product_uom):
        if self.pack_uom_id:
            return False
        return super()._is_applicable_for(product, qty_in_product_uom)

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['pack_uom_id']