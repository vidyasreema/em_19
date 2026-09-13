from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_manufacture_route = fields.Boolean(
        string='POS Manufacturing Flag',
        compute='_compute_is_manufacture_route',
        store=True,
        help="True when the 'Manufacture' route applies to this product, "
             "either directly under Routes or through its product category. "
             "This flag identifies products that trigger the 'add raw "
             "material' button when sold at POS. It does NOT restrict which "
             "products can be picked as raw materials inside the popup — "
             "any product is selectable there.",
    )

    @api.depends(
        'route_ids',
        'route_ids.rule_ids.action',
        'categ_id',
        'categ_id.total_route_ids',
        'categ_id.total_route_ids.rule_ids.action',
    )
    def _compute_is_manufacture_route(self):
        for product in self:
            # A product can inherit the Manufacture route from its category
            # instead of having it set directly, in which case the POS button
            # would never appear.
            routes = product.route_ids | product.categ_id.total_route_ids
            product.is_manufacture_route = any(
                rule.action == 'manufacture'
                for route in routes
                for rule in route.rule_ids
            )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        fields_list.append('is_manufacture_route')
        return fields_list