from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_manufacture_route = fields.Boolean(
        string='POS Manufacturing Flag',
        compute='_compute_is_manufacture_route',
        store=True,
        help="True when the existing 'Manufacture' checkbox under Routes "
             "is ticked. This flag identifies products that trigger the "
             "'add raw material' button when sold at POS. It does NOT "
             "restrict which products can be picked as raw materials "
             "inside the popup — any product is selectable there.",
    )

    @api.depends('route_ids', 'route_ids.rule_ids.action')
    def _compute_is_manufacture_route(self):
        for product in self:
            product.is_manufacture_route = any(
                rule.action == 'manufacture'
                for route in product.route_ids
                for rule in route.rule_ids
            )

    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        fields.append('is_manufacture_route')
        return fields