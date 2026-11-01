# -*- coding: utf-8 -*-
import logging

from odoo import fields, http
from odoo.http import request

from odoo.addons.website_sale.controllers.payment import PaymentPortal

_logger = logging.getLogger(__name__)


class DeliveryTimingController(http.Controller):

    @http.route('/shop/delivery/timing', type='jsonrpc', auth='public', website=True)
    def get_delivery_timing(self, carrier_id=None, address_id=None, **kwargs):
        """Delivery promise shown on the checkout pages (banner and popup).

        :param int carrier_id: the delivery method selected on the page;
            the delivery method of the cart if not given
        """
        try:
            if carrier_id:
                carrier = request.env['delivery.carrier'].sudo().browse(int(carrier_id)).exists()
            else:
                cart = request.cart
                carrier = cart.carrier_id.sudo() if cart else request.env['delivery.carrier']
            if not carrier:
                return self._empty_response()

            store_settings = request.env['store.settings'].sudo()._find_for_website(request.website)
            if not store_settings:
                _logger.error("No store settings found")
                return self._empty_response()

            promise = carrier._get_delivery_promise(store_settings)
            return {
                'scenario':      promise['scenario'],
                'show_message':  bool(promise['message']),
                'show_popup':    promise['show_popup'],
                'message':       promise['message'],
                'delivery_date': promise['delivery_date'],
                'date_label':    promise['date_label'],
                'opening_time':  promise['opening_time'],
                'address_id':    address_id,
            }

        except Exception as e:
            _logger.exception(f"Error in get_delivery_timing: {e}")
            return self._empty_response()

    @http.route('/shop/save_delivery_timing', type='jsonrpc', auth='public', website=True)
    def save_delivery_timing(self, **kwargs):
        """Save the delivery promise on the current cart, so it is visible in the
        backend before payment. Computed on the server: values sent by the page
        are ignored. It is saved again when the customer pays (order time)."""
        # Odoo 19: the current cart is request.cart (sale_get_order() was removed)
        order = request.cart
        if not order:
            return {'success': False, 'error': 'No active order found'}

        order._store_delivery_promise()
        if not order.delivery_promise_until:
            return {'success': False, 'error': 'No delivery promise for this order'}
        return {
            'success':         True,
            'order_id':        order.id,
            'commitment_date': fields.Datetime.to_string(order.commitment_date),
        }

    def _empty_response(self):
        return {
            'scenario':      0,
            'show_message':  False,
            'show_popup':    False,
            'delivery_date': None,
            'opening_time':  '',
            'message':       '',
        }


class PaymentPortalDeliveryPromise(PaymentPortal):

    def _validate_transaction_for_order(self, transaction, sale_order):
        """The customer clicked "Pay": this is the order time of the promise."""
        super()._validate_transaction_for_order(transaction, sale_order)
        sale_order._store_delivery_promise()
