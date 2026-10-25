from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request, route

from odoo.addons.portal.controllers.portal import CustomerPortal


def _answer(order_sudo, source_id):
    """Save the answer of the customer, if it is one of the answers shown."""
    if request.website.order_source_question and str(source_id or '').isdigit():
        source = request.env['website.order.source'].sudo().browse(int(source_id)).exists()
        if source.active:
            order_sudo._order_source_answer(source)


class WebsiteOrderSource(http.Controller):

    @route('/shop/order/source', type='http', auth='public', website=True, methods=['POST'], sitemap=False)
    def order_source_answer(self, source_id=None, **post):
        """One tap on the confirmation page: the answer of the order just placed."""
        order_id = request.session.get('sale_last_order_id')
        order_sudo = request.env['sale.order'].sudo().browse(order_id).exists() if order_id else None
        if order_sudo:
            _answer(order_sudo, source_id)
        return request.redirect('/shop/confirmation#o_order_source')


class OrderSourcePortal(CustomerPortal):

    @route('/my/orders/<int:order_id>/source', type='http', auth='public', website=True,
           methods=['POST'], sitemap=False)
    def portal_order_source_answer(self, order_id, source_id=None, access_token=None, back=None, **post):
        """One tap on the order page or on Track your order (My Orders, or the link of an email)."""
        try:
            order_sudo = self._document_check_access('sale.order', order_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        if order_sudo.website_id and order_sudo.state == 'sale':
            _answer(order_sudo, source_id)
        if back == 'track':
            return request.redirect(order_sudo.get_portal_url(suffix='/track', anchor='o_order_source'))
        return request.redirect(order_sudo.get_portal_url(anchor='o_order_source'))
