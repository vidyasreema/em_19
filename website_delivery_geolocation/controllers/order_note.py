from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleCustom(WebsiteSale):

    @http.route(['/shop/save_order_note'], type='json', auth='public', website=True)
    def save_order_note(self, order_note='', **kwargs):
        order = request.website.sale_get_order()
        if order:
            order.sudo().write({'order_note': order_note})
            return {'success': True}
        return {'success': False}