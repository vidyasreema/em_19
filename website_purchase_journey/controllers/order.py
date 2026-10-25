import json
import re
from urllib.parse import quote_plus

from werkzeug.urls import url_encode

import logging

from odoo import _
from odoo.http import request, route

from odoo.addons.auth_signup.models.res_users import SignupError
from odoo.addons.website_sale.controllers.cart import Cart
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
ORDER_PATH = '/shop/order'

SESSION_GUEST = 'journey_checkout_as_guest'
SESSION_WELCOME_APPLIED = 'journey_welcome_applied'
SESSION_COUPON_ERROR = 'journey_coupon_error'


def journey_apply_code(order_sudo, code):
    """Apply a coupon / promotion code like the cart does. :return: an error or None"""
    status = order_sudo._try_apply_code(code)
    if status.get('not_found'):
        return _("This code doesn't exist. Check the spelling or pick one from your coupons.")
    if status.get('error'):
        return status['error']
    if len(status) == 1:
        coupon, rewards = next(iter(status.items()))
        if len(rewards) == 1 and not rewards.multi_product:
            result = order_sudo._apply_program_reward(rewards, coupon)
            if 'error' in result:
                return result['error']
    order_sudo._update_programs_and_rewards()
    return None


class JourneyCart(Cart):

    @route()
    def cart(self, id=None, access_token=None, revive_method='', **post):
        """The cart is the single order page (an abandoned cart link keeps the standard flow)."""
        if request.website.journey_enabled and not id:
            return request.redirect(ORDER_PATH)
        return super().cart(id=id, access_token=access_token, revive_method=revive_method, **post)


class JourneyCheckout(WebsiteSale):

    # ──────────────────────────────────────────────────────────────────────────
    # The standard steps lead to the order page
    # ──────────────────────────────────────────────────────────────────────────

    @route()
    def shop_checkout(self, try_skip_step=None, **query_params):
        if request.website.journey_enabled:
            return request.redirect(ORDER_PATH)
        return super().shop_checkout(try_skip_step=try_skip_step, **query_params)

    @route()
    def shop_payment(self, **post):
        if request.website.journey_enabled:
            return request.redirect(ORDER_PATH)
        return super().shop_payment(**post)

    # ──────────────────────────────────────────────────────────────────────────
    # The order page
    # ──────────────────────────────────────────────────────────────────────────

    @route(ORDER_PATH, type='http', auth='public', website=True, sitemap=False)
    def journey_order(self, **kwargs):
        website = request.website
        if not website.journey_enabled:
            return request.redirect('/shop/cart')
        order_sudo = request.cart
        if not order_sudo or order_sudo.state != 'draft' or not order_sudo.website_order_line:
            return request.render('website_purchase_journey.order_page_empty', {})
        if request.env.user._is_public() and website.account_on_checkout == 'mandatory':
            return request.redirect('/web/login?' + url_encode({'redirect': ORDER_PATH}))

        # Like the standard checkout: after the payment, /shop/payment/validate finds
        # the order with this key (the cart is already cleared from the session).
        request.session['sale_last_order_id'] = order_sudo.id
        self._journey_prepare_order(order_sudo)
        return request.render('website_purchase_journey.order_page', self._journey_order_values(order_sudo))

    def _journey_prepare_order(self, order_sudo):
        """Delivery method of the address (zone), prices, rewards, welcome coupon."""
        if not order_sudo._is_anonymous_cart() and order_sudo._has_deliverable_products():
            available = order_sudo._get_delivery_methods()
            if delivery_method := order_sudo._get_preferred_delivery_method(available):
                rate = delivery_method.rate_shipment(order_sudo)
                if (
                    not order_sudo.carrier_id
                    or not rate.get('success')
                    or order_sudo.amount_delivery != rate['price']
                ):
                    order_sudo._set_delivery_method(delivery_method, rate=rate)
        order_sudo._recompute_cart()
        order_sudo._update_programs_and_rewards()
        order_sudo._auto_apply_rewards()
        self._journey_apply_welcome_coupon(order_sudo)

    def _journey_apply_welcome_coupon(self, order_sudo):
        """Right after signing up, the welcome coupon is applied to the cart (once)."""
        user = request.env.user
        program = request.website.sudo().journey_welcome_program_id.filtered('active')
        if user._is_public() or not program or request.session.get(SESSION_WELCOME_APPLIED):
            return
        request.session[SESSION_WELCOME_APPLIED] = True
        card = request.env['loyalty.card'].sudo().search([
            ('program_id', '=', program.id), ('partner_id', '=', user.partner_id.id), ('points', '>', 0),
        ], limit=1)
        if card and card not in order_sudo.applied_coupon_ids:
            self._journey_apply_code(order_sudo, card.code)

    def _journey_apply_code(self, order_sudo, code):
        return journey_apply_code(order_sudo, code)

    def _journey_oauth_providers(self):
        """Google / Facebook sign-in buttons, coming back to the order page."""
        providers = request.env['auth.oauth.provider'].sudo().search_read(
            [('enabled', '=', True)], ['name', 'client_id', 'auth_endpoint', 'scope', 'css_class'])
        url_root = request.httprequest.url_root
        for provider in providers:
            state = {'d': request.session.db, 'p': provider['id'], 'r': quote_plus(url_root + ORDER_PATH[1:])}
            params = {
                'response_type': 'token',
                'client_id': provider['client_id'],
                'redirect_uri': url_root + 'auth_oauth/signin',
                'scope': provider['scope'],
                'state': json.dumps(state),
            }
            provider['auth_link'] = '%s?%s' % (provider['auth_endpoint'], url_encode(params))
        return providers

    def _journey_promise_values(self, order_sudo):
        """Promise of the order, and whether the delivery method asks for a
        popup (the page skips it on its own reloads when the promise is the same)."""
        promise = order_sudo._get_delivery_promise() if order_sudo.carrier_id else {}
        return promise, bool(promise and promise['show_popup'])

    def _journey_order_values(self, order_sudo):
        website = request.website
        is_public = request.env.user._is_public()
        values = self._get_shop_payment_values(order_sudo)
        has_address = not order_sudo._is_anonymous_cart()
        if not has_address:
            # No address yet, so no delivery zone: "unable to ship" would be wrong.
            # The order button asks for the address instead.
            values['errors'] = []
        if values['errors']:
            values.pop('payment_methods_sudo', '')
            values.pop('tokens_sudo', '')
        promise, show_popup = self._journey_promise_values(order_sudo)
        addresses = request.env['res.partner']
        if not is_public:
            commercial = order_sudo.partner_id.commercial_partner_id
            addresses = request.env['res.partner'].sudo().search([
                ('id', 'child_of', commercial.id), ('type', 'in', ('delivery', 'other')),
            ]) | order_sudo.partner_id
            addresses = addresses.filtered(lambda p: p.street)
        values.update({
            'website': website,
            'summary': order_sudo._journey_summary(website),
            'promise': promise,
            'show_promise_popup': show_popup,
            'zone': website._journey_find_zone(
                order_sudo.partner_shipping_id.partner_latitude, order_sudo.partner_shipping_id.partner_longitude,
            ) if has_address and order_sudo.partner_shipping_id.partner_latitude else request.env['delivery.zone'],
            'has_address': has_address,
            'shipping': order_sudo.partner_shipping_id if has_address else request.env['res.partner'],
            'addresses': addresses,
            'address_labels': dict(request.env['res.partner']._fields['address_label']._description_selection(request.env)),
            'is_public': is_public,
            'guest_mode': bool(request.session.get(SESSION_GUEST)),
            'oauth_providers': self._journey_oauth_providers() if is_public else [],
            'signup_url': '/web/signup?' + url_encode({'redirect': ORDER_PATH}),
            'coupon_error': request.session.pop(SESSION_COUPON_ERROR, None),
            'contact_email': '' if is_public and not has_address else order_sudo.partner_id.email or '',
            'consent': order_sudo.partner_id.marketing_consent if has_address or not is_public else False,
            'only_services': order_sudo.only_services,
        })
        return values

    # ──────────────────────────────────────────────────────────────────────────
    # Actions of the order page (the page reloads afterwards)
    # ──────────────────────────────────────────────────────────────────────────

    @route('/shop/order/coupon', type='jsonrpc', auth='public', website=True, methods=['POST'])
    def journey_order_coupon(self, code):
        order_sudo = request.cart
        code = (code or '').strip()
        if not order_sudo or not code:
            return {'error': _("Enter a code.")}
        error = self._journey_apply_code(order_sudo, code)
        if error:
            request.session[SESSION_COUPON_ERROR] = error
        return {'ok': not error, 'error': error}

    @route('/shop/order/coupon/remove', type='jsonrpc', auth='public', website=True, methods=['POST'])
    def journey_order_coupon_remove(self, line_id):
        order_sudo = request.cart
        if order_sudo:
            lines = order_sudo.order_line.filtered(lambda l: l.id == int(line_id) and l.is_reward_line)
            if lines:
                lines.unlink()
                order_sudo._update_programs_and_rewards()
        return {'ok': True}

    @route('/shop/order/guest', type='jsonrpc', auth='public', website=True, methods=['POST'])
    def journey_order_guest(self, guest=True):
        """Continue as guest (the sign-up box shrinks to one line) or show it again."""
        request.session[SESSION_GUEST] = bool(guest)
        return {'ok': True}

    @route('/shop/order/prepare', type='jsonrpc', auth='public', website=True, methods=['POST'])
    def journey_order_prepare(self, email=None, consent=False, leave_at_door=False,
                              call_on_arrival=False, note='', save_note=False):
        """Save the form and check the order before the payment starts."""
        order_sudo = request.cart
        if not order_sudo or order_sudo.state != 'draft' or not order_sudo.website_order_line:
            return {'error': _("Your cart has changed. Please check your order."), 'reload': True}
        if order_sudo._is_anonymous_cart():
            return {'error': _("Add your delivery address."), 'field': 'address'}
        partner_sudo = order_sudo.partner_id
        if request.env.user._is_public():
            email = (email or '').strip()
            if not EMAIL_RE.match(email):
                return {'error': _("Enter a valid email address."), 'field': 'email'}
            if partner_sudo.email != email:
                partner_sudo.email = email
        partner_sudo._journey_set_marketing_consent(consent)

        note = (note or '').strip()[:1000]
        order_sudo.write({
            'order_note': note,
            'delivery_leave_at_door': bool(leave_at_door),
            'delivery_call_on_arrival': bool(call_on_arrival),
        })
        shipping_sudo = order_sudo.partner_shipping_id
        if save_note and shipping_sudo and note != (shipping_sudo.delivery_directions or ''):
            shipping_sudo.delivery_directions = note

        if errors := self._get_shop_payment_errors(order_sudo):
            return {'error': errors[0][1]}
        return {'ok': True}

    # ── "Address details" sheet (View cart, Change / Add on the order page) ─

    @route('/shop/journey/address', type='jsonrpc', auth='public', website=True, methods=['POST'])
    def journey_save_address(self, apartment='', building='', directions='', label='home', name='', phone='',
                             latitude=None, longitude=None, partner_id=None,
                             area='', city='', state='', country_code=''):
        """Save the delivery address of the cart: a new one, or the one being
        changed (partner_id). The pin is the one of the sheet, else the one of
        the "Deliver to" bar. :return: {'ok'} or {'error', 'field'}"""
        website = request.website
        order_sudo = request.cart
        if not order_sudo or order_sudo.state != 'draft' or not order_sudo.website_order_line:
            return {'error': _("Your cart is empty."), 'field': ''}
        try:
            point = (float(latitude), float(longitude))
        except (TypeError, ValueError):
            point = website._journey_session_point()
        if not point or not (-90 <= point[0] <= 90 and -180 <= point[1] <= 180):
            return {'error': _("Set your delivery location first."), 'field': 'pin'}
        if not website._journey_find_zone(*point):
            return {'error': _("Sorry, we don't deliver to this location yet. Please move the pin."), 'field': 'pin'}
        apartment, building, name, phone = (
            (value or '').strip()[:120] for value in (apartment, building, name, phone))
        for field, value, message in (
            ('apartment', apartment, _("Enter the apartment or villa number so the driver can find you.")),
            ('building', building, _("Enter the building or tower name.")),
            ('name', name, _("Enter the name of the person receiving the order.")),
            ('phone', phone, _("Enter the mobile number of the person receiving the order.")),
        ):
            if not value:
                return {'error': message, 'field': field}

        PartnerSudo = request.env['res.partner'].with_context(show_address=1).sudo()
        address_sudo = PartnerSudo
        if partner_id:
            address_sudo = PartnerSudo.browse(int(partner_id)).exists()
            if not address_sudo or not address_sudo._can_be_edited_by_current_customer(order_sudo=order_sudo):
                return {'error': _("This address can't be changed. Add a new one instead."), 'field': ''}

        values = website._journey_address_values(
            apartment, building, point, area=(area or '').strip()[:80], city=(city or '').strip()[:80],
            state=(state or '').strip()[:80], country_code=(country_code or '').strip()[:2])
        values.update({
            'address_label': label if label in ('home', 'work', 'other') else 'home',
            'delivery_directions': (directions or '').strip()[:1000],
        })
        phone, error = PartnerSudo._journey_check_phone(phone, mobile=True)
        if error:
            return {'error': error, 'field': 'phone'}

        if order_sudo._is_anonymous_cart():
            # Guest: the address is the customer too (the email is asked on the order page)
            address_sudo, _feedback = self._create_or_update_address(
                PartnerSudo, address_type='delivery', use_delivery_as_billing=True,
                verify_address_values=False, order_sudo=order_sudo, name=name, phone=phone, **values)
            order_sudo._update_address(address_sudo.id, {'partner_id', 'partner_invoice_id', 'partner_shipping_id'})
            order_sudo.message_unsubscribe(website.partner_id.ids)
            return {'ok': True}

        customer_sudo = order_sudo.partner_id
        is_member = not request.env.user._is_public()
        if address_sudo and not (is_member and address_sudo == customer_sudo):
            # A delivery address (or the guest's own): changed as typed
            address_sudo.write(dict(values, name=name, phone=phone))
            shipping_sudo = address_sudo
        else:
            if is_member and (address_sudo == customer_sudo or not customer_sudo.street):
                # The member's own address (the first one is also the billing
                # address): their account keeps its name and mobile
                customer_sudo.write(dict(values, **({} if customer_sudo.phone else {'phone': phone})))
            same_receiver = (
                customer_sudo.name == name
                and re.sub(r'\D', '', PartnerSudo._journey_check_phone(customer_sudo.phone)[0])
                == re.sub(r'\D', '', phone)
            )
            if customer_sudo.street == values['street'] and same_receiver:
                shipping_sudo = customer_sudo
            else:
                shipping_sudo, _feedback = self._create_or_update_address(
                    PartnerSudo, address_type='delivery', verify_address_values=False, order_sudo=order_sudo,
                    name=name, phone=phone, email=customer_sudo.email or '', **values)
        order_sudo._update_address(shipping_sudo.id, {'partner_shipping_id'})
        return {'ok': True}

    # ── After the order: sign up from the confirmation page (v2 §4.1) ──────

    @route('/shop/order/signup', type='http', auth='public', website=True, methods=['POST'], sitemap=False)
    def journey_order_signup(self, **post):
        order_id = request.session.get('sale_last_order_id')
        order_sudo = request.env['sale.order'].sudo().browse(order_id).exists() if order_id else None
        if not order_sudo or not request.env.user._is_public() or not order_sudo._journey_can_sign_up():
            return request.redirect('/shop/confirmation')
        try:
            order_sudo._journey_sign_up()
        except (SignupError, ValueError):
            _logger.exception("Sign-up after the order %s failed", order_sudo.name)
            return request.redirect('/shop/confirmation?journey_signup=error')
        return request.redirect('/shop/confirmation?journey_signup=done')
