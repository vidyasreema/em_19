from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleCustom(WebsiteSale):

    @http.route(['/shop/save_order_note'], type='jsonrpc', auth='public', website=True)
    def save_order_note(self, order_note='', **kwargs):
        # Odoo 19: the current cart is request.cart (sale_get_order() was removed)
        order = request.cart
        if order:
            order.sudo().write({'order_note': order_note})
            return {'success': True}
        return {'success': False}