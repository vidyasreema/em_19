from odoo import api, models

# App roots hidden from operational staff, who work only in the operational app.
HIDDEN_ROOT_XMLIDS = ('stock.menu_stock_root', 'stock_barcode.stock_barcode_menu')


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _visible_menu_ids(self, debug=False):
        visible_ids = super()._visible_menu_ids(debug=debug)
        user = self.env.user
        if not user.has_group('stock_barcode_register.group_operational_staff') or user.has_group('stock.group_stock_manager'):
            return visible_ids
        root_ids = [
            res_id for xmlid in HIDDEN_ROOT_XMLIDS
            if (res_id := self.env['ir.model.data']._xmlid_to_res_id(xmlid, raise_if_not_found=False))
        ]
        if not root_ids:
            return visible_ids
        hidden_ids = self.sudo().with_context(active_test=False).search([('id', 'child_of', root_ids)]).ids
        return visible_ids - frozenset(hidden_ids)
