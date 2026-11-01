from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import format_amount


class PurchaseJourney(http.Controller):

    @http.route('/shop/journey/weights', type='jsonrpc', auth='public', website=True, readonly=True)
    def journey_weights(self, product_template_id):
        """Rows of the "Choose weight" sheet of a published product."""
        website = request.website
        template = request.env['product.template'].search(
            [('id', '=', int(product_template_id))] + website.sale_product_domain(), limit=1)
        if not template:
            return {'html': '', 'cart_qty': 0}
        html = request.env['ir.ui.view']._render_template('website_purchase_journey.weight_sheet_rows', {
            'website': website,
            'product': template,
            'rows': template._journey_weight_rows(website),
        })
        return {
            'html': html,
            'name': template.display_name,
            'cart_qty': website._journey_cart_quantities()['templates'].get(template.id, 0),
        }

    @http.route('/shop/journey/cart_total', type='jsonrpc', auth='public', website=True, readonly=True)
    def journey_cart_total(self):
        """Quantity and total of the cart, for the "View cart" button."""
        cart = request.cart
        if not cart:
            return {'quantity': 0, 'amount': '', 'needs_address': False}
        return {
            'quantity': int(cart.cart_quantity),
            'amount': format_amount(request.env, cart.amount_total, cart.currency_id),
            'needs_address': request.website._journey_cart_needs_address(cart),
        }

    @http.route('/shop/journey/set_location', type='jsonrpc', auth='public', website=True, methods=['POST'])
    def journey_set_location(self, latitude, longitude, area=''):
        """Location of the visitor (browser permission or map): saved for the
        visit, it gives the delivery promise and starts the first address."""
        try:
            lat, lng = float(latitude), float(longitude)
        except (TypeError, ValueError):
            raise UserError(_("Invalid location, please set it again."))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise UserError(_("Invalid location, please set it again."))
        website = request.website
        website._journey_set_location(lat, lng, area)
        values = website._journey_location_values()
        return {
            'zone_found': values['zone_found'],
            'area': values['area'],
            'bar_html': request.env['ir.ui.view']._render_template(
                'website_purchase_journey.location_bar_content', {'website': website, 'location': values}),
        }
