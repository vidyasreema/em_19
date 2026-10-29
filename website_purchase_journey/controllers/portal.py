from odoo import _
from odoo.exceptions import AccessError, MissingError
from odoo.http import request, route

from odoo.addons.website_sale.controllers.reorder import CustomerPortal

from .order import ORDER_PATH, SESSION_COUPON_ERROR, journey_apply_code


class JourneyPortal(CustomerPortal):

    @route('/my/coupons', type='http', auth='user', website=True)
    def journey_my_coupons(self, **kwargs):
        """My Account > My coupons (Annex 3 C5)."""
        current, past = request.env['loyalty.card']._journey_portal_coupons(
            request.env.user.partner_id, cart=request.cart)
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'journey_coupons',
            'current_coupons': current,
            'past_coupons': past,
            'coupon_error': request.session.pop(SESSION_COUPON_ERROR, None),
            'new_coupons': [coupon for coupon in current if coupon['new']],
        })
        return request.render('website_purchase_journey.portal_my_coupons', values)

    @route('/my/coupons/celebrated', type='jsonrpc', auth='user', website=True, methods=['POST'])
    def journey_my_coupons_celebrated(self, card_ids):
        """The "new coupon" party was shown: not again for these coupons."""
        partner = request.env.user.partner_id
        request.env['loyalty.card'].sudo().search([
            ('id', 'in', [int(card_id) for card_id in card_ids]),
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
        ]).journey_celebrated = True
        return True

    @route('/my/coupons/apply', type='http', auth='user', website=True, methods=['POST'])
    def journey_my_coupons_apply(self, card_id, **kwargs):
        """Apply to my order: the coupon goes on the cart and the order page opens."""
        partner = request.env.user.partner_id
        card = request.env['loyalty.card'].sudo().search([
            ('id', '=', int(card_id)),
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
        ], limit=1)
        order_sudo = request.cart
        if not card or not order_sudo or not order_sudo.website_order_line:
            request.session[SESSION_COUPON_ERROR] = _("Add products to your cart first.")
            return request.redirect('/my/coupons')
        if card not in order_sudo.applied_coupon_ids:
            if error := journey_apply_code(order_sudo, card.code):
                request.session[SESSION_COUPON_ERROR] = error
        return request.redirect(ORDER_PATH)

    @route('/my/orders/<int:order_id>/track', type='http', auth='public', website=True, sitemap=False)
    def journey_order_track(self, order_id, access_token=None, **kwargs):
        """Track your order / Order details (Annex 3 C6, v2 §7)."""
        try:
            order_sudo = self._document_check_access('sale.order', order_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        if order_sudo.state not in ('sale', 'cancel'):
            return request.redirect('/my/orders')
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'journey_track',
            # Not "order": the Purchase breadcrumb of the portal reacts to it
            'track_order': order_sudo,
            'summary': order_sudo._journey_summary(order_sudo.website_id or request.website),
            'step': order_sudo._journey_track_step(),
            'access_token': access_token,
        })
        return request.render('website_purchase_journey.portal_order_track', values)

    @route('/shop/order/reorder', type='jsonrpc', auth='public', website=True, methods=['POST'])
    def journey_order_reorder(self, order_id, access_token=None, mode='ask'):
        """Order again (Annex 3 C7). When the cart already has other products,
        the customer chooses first: mode 'replace' (the cart becomes the past
        order) or 'add' (Odoo's reorder: added to the cart)."""
        try:
            order_sudo = self._document_check_access('sale.order', order_id, access_token=access_token)
        except (AccessError, MissingError):
            return {'error': _("This order cannot be found.")}
        cart_sudo = request.cart
        cart_lines = cart_sudo._journey_product_lines() if cart_sudo else request.env['sale.order.line']
        if cart_lines and mode == 'ask':
            return {'ask': True, 'cart_count': int(sum(cart_lines.mapped('product_uom_qty')))}
        if cart_lines and mode == 'replace':
            for line in cart_lines:
                cart_sudo._cart_update_line_quantity(line.id, 0)
        if not order_sudo._is_reorder_allowed():
            return {'error': _("These products cannot be ordered again.")}
        values = self.my_orders_reorder(order_id, access_token=access_token)
        return {'cart_quantity': values['cart_quantity']}

    def _validate_address_values(self, address_values, partner_sudo, address_type, *args, **kwargs):
        """The phone of the account and address forms is a UAE number (stored
        in its international format), like the one of the address sheet."""
        invalid_fields, missing_fields, error_messages = super()._validate_address_values(
            address_values, partner_sudo, address_type, *args, **kwargs)
        if request.website.journey_enabled and address_values.get('phone') and 'phone' not in invalid_fields:
            phone, error = request.env['res.partner']._journey_check_phone(address_values['phone'])
            if error:
                invalid_fields.add('phone')
                error_messages.append(error)
            else:
                address_values['phone'] = phone
        return invalid_fields, missing_fields, error_messages
