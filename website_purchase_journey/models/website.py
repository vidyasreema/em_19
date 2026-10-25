import json
import re
from collections import defaultdict
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.http import request
from odoo.tools import format_amount

from odoo.addons.website_sale_meta_feed.models.product_feed import OUT_OF_STOCK_RIBBON_NAMES

SESSION_LAT = 'journey_latitude'
SESSION_LNG = 'journey_longitude'
SESSION_AREA = 'journey_area'

# The checkout pages show the promise themselves: no location bar there.
CHECKOUT_PATHS = ('/shop/address', '/shop/checkout', '/shop/extra_info', '/shop/payment', '/shop/confirmation')


class Website(models.Model):
    _inherit = 'website'

    journey_enabled = fields.Boolean(
        string='New Purchase Journey',
        default=True,
        help='Add from the shop, weight choice and location on entry. '
             'Untick to go back to the standard Odoo shop at once.',
    )
    journey_general_promise = fields.Char(
        string='General Delivery Message',
        translate=True,
        default='Same-day delivery in Abu Dhabi for orders before 7:00 PM',
        help='Shown in the "Deliver to" bar while the customer has not set a location.',
    )
    journey_whatsapp_number = fields.Char(
        string='WhatsApp Help Number',
        help='Number opened by "Need help? Chat on WhatsApp" in My Account and on the order pages, '
             'with the country code (e.g. +971 50 717 9729). Empty: no WhatsApp button.',
    )
    journey_welcome_program_id = fields.Many2one(
        'loyalty.program',
        string='Welcome Coupon at Sign-up',
        domain=[('program_type', '=', 'coupons')],
        help='Every new customer account gets one coupon of this program. '
             'Its discount is shown to guests at checkout ("Sign up and save AED X").',
    )

    def _journey_whatsapp_url(self, text=''):
        """wa.me link of the help number ('' when no number is set)."""
        self.ensure_one()
        digits = re.sub(r'\D', '', self.journey_whatsapp_number or '')
        if not digits:
            return ''
        url = 'https://wa.me/%s' % digits
        return '%s?text=%s' % (url, quote(text)) if text else url

    @api.model
    def _journey_set_default_welcome_program(self):
        program = self.env.ref('website_purchase_journey.loyalty_program_welcome_signup', raise_if_not_found=False)
        if program:
            self.search([('journey_welcome_program_id', '=', False)]).journey_welcome_program_id = program

    # ──────────────────────────────────────────────────────────────────────────
    # Availability: the Out of stock ribbon is the single source (Annex 3 §9)
    # ──────────────────────────────────────────────────────────────────────────

    def _journey_out_of_stock_ribbons(self):
        """The ribbons the product feed of this website sends as out of stock."""
        self.ensure_one()
        # Cached for the request (transaction): asked once per product card
        cache = self.env.cr.cache.setdefault('journey_out_of_stock_ribbons', {})
        if self.id not in cache:
            feeds = self.env['product.feed'].sudo().search([('website_id', 'in', (False, self.id))])
            ribbons = feeds.out_of_stock_ribbon_ids
            if not ribbons:
                ribbons = self.env['product.ribbon'].sudo().with_context(lang='en_US').search(Domain.OR(
                    Domain('name', '=ilike', name) for name in OUT_OF_STOCK_RIBBON_NAMES))
            cache[self.id] = ribbons.ids
        return self.env['product.ribbon'].browse(cache[self.id])

    def _journey_cart_quantities(self):
        """{'templates': {template id: qty}, 'variants': {product id: qty}} of the current cart."""
        templates, variants = defaultdict(float), defaultdict(float)
        cart = request.cart if request else None
        if cart:
            for line in cart.order_line.filtered(lambda l: l.product_id and not l.is_delivery and not l.display_type):
                templates[line.product_id.product_tmpl_id.id] += line.product_uom_qty
                variants[line.product_id.id] += line.product_uom_qty
        return {'templates': templates, 'variants': variants}

    # ──────────────────────────────────────────────────────────────────────────
    # Location on entry and "Deliver to" bar
    # ──────────────────────────────────────────────────────────────────────────

    def _journey_active_order(self):
        """Open online order of the visitor, for the tracking bar of the shop:
        their latest one not delivered yet (guests: the order just placed)."""
        self.ensure_one()
        Order = self.env['sale.order'].sudo()
        if not self.journey_enabled:
            return Order
        domain = Domain([
            ('website_id', '=', self.id),
            ('state', '=', 'sale'),
            ('stage_id', '!=', False),
            ('stage_id.code', 'not in', ('delivered', 'completed', 'cancelled')),
        ])
        if self.env.user._is_public():
            order_id = request and request.session.get('sale_last_order_id')
            if not order_id:
                return Order
            domain &= Domain('id', '=', order_id)
        else:
            domain &= Domain('partner_id', 'child_of', self.env.user.partner_id.commercial_partner_id.id)
        return Order.search(domain, order='date_order desc, id desc', limit=1)

    def _journey_show_location_bar(self):
        if not (request and self.journey_enabled):
            return False
        path = request.httprequest.path
        return not any(page in path for page in CHECKOUT_PATHS)

    def _journey_cart_bar_values(self):
        """"View cart · N items · total" button at the bottom of the shop pages
        (not on the order, checkout and account pages). Empty cart: hidden."""
        if not (request and self.journey_enabled):
            return None
        path = request.httprequest.path
        if any(page in path for page in CHECKOUT_PATHS) or path.startswith(('/my', '/web', '/shop/order', '/shop/cart')):
            return None
        cart = request.cart
        quantity = int(cart.cart_quantity) if cart else 0
        return {
            'quantity': quantity,
            'amount': format_amount(self.env, cart.amount_total, cart.currency_id) if cart else '',
            'needs_address': self._journey_cart_needs_address(cart),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # "Address details" sheet of the View cart button
    # ──────────────────────────────────────────────────────────────────────────

    def _journey_cart_needs_address(self, cart):
        """Whether View cart asks for the delivery address first (the cart has none yet)."""
        if not cart or cart.only_services:
            return False
        return cart._is_anonymous_cart() or not cart.partner_shipping_id.street

    def _journey_address_sheet_values(self):
        """Pin, receiver name and mobile a new address starts with."""
        self.ensure_one()
        point = self._journey_session_point()
        location = self._journey_location_values()
        partner = self.env.user.partner_id
        is_public = self.env.user._is_public()
        return {
            'latitude': point[0] if point else '',
            'longitude': point[1] if point else '',
            'area': location['area'],
            'name': '' if is_public else partner.name or '',
            'phone': '' if is_public else partner.phone or '',
        }

    def _journey_address_data(self, partner):
        """An address in the fields of the sheet (JSON, for its Change / Edit buttons).
        The street is "apartment, building": the last part is the building."""
        apartment, separator, building = (partner.street or '').rpartition(', ')
        if not separator:
            apartment, building = '', partner.street or ''
        return json.dumps({
            'partner_id': partner.id,
            'apartment': apartment,
            'building': building,
            'directions': partner.delivery_directions or '',
            'label': partner.address_label or 'home',
            'name': partner.name or '',
            'phone': partner.phone or '',
            'latitude': partner.partner_latitude or '',
            'longitude': partner.partner_longitude or '',
            'area': partner.street2 or partner.city or '',
        })

    def _journey_address_values(self, apartment, building, point, area='', city='', state='', country_code=''):
        """Address fields of a pin: street from the apartment and the building;
        city, emirate and country from the map, else from the company.
        :param tuple point: (latitude, longitude) of the pin
        :return: res.partner values"""
        self.ensure_one()
        company = self.company_id
        Country = self.env['res.country'].sudo()
        country = country_code and Country.search([('code', '=', country_code.upper())], limit=1)
        country = country or company.country_id
        city = city or company.city or ''
        states = self.env['res.country.state'].sudo().search([('country_id', '=', country.id)])
        state_record = (
            (state and states.filtered(lambda s: s.name.lower() == state.lower() or state.lower() in s.name.lower()))
            or (city and states.filtered(lambda s: s.name.lower() == city.lower()))
            or company.state_id.filtered(lambda s: s in states)
        )[:1]
        return {
            'street': '%s, %s' % (apartment, building),
            'street2': area or self._journey_find_zone(*point).name or '',
            'city': city,
            'country_id': country.id,
            'state_id': state_record.id,
            'zip': '00000' if country.zip_required else '',
            'partner_latitude': point[0],
            'partner_longitude': point[1],
        }

    def _journey_session_point(self):
        lat, lng = request.session.get(SESSION_LAT), request.session.get(SESSION_LNG)
        return (lat, lng) if lat and lng else None

    def _journey_set_location(self, latitude, longitude, area=''):
        request.session[SESSION_LAT] = latitude
        request.session[SESSION_LNG] = longitude
        request.session[SESSION_AREA] = (area or '').strip()[:80]

    def _journey_find_zone(self, latitude, longitude):
        zones = self.env['delivery.zone'].sudo().search([
            ('active', '=', True), ('polygon', '!=', False), ('delivery_method_id', '!=', False)])
        for zone in zones:
            if zone.is_location_in_zone(latitude, longitude):
                return zone
        return self.env['delivery.zone']

    def _journey_location_values(self):
        """What the "Deliver to" bar shows: the area and the delivery promise
        of the zone of the customer's location, or the general message."""
        self.ensure_one()
        point = self._journey_session_point()
        values = {
            'has_location': bool(point),
            'area': request.session.get(SESSION_AREA) or '',
            'zone_found': False,
            'message': self.journey_general_promise or '',
        }
        if not point:
            return values
        zone = self._journey_find_zone(*point)
        if not zone:
            values['message'] = _("We don't deliver to this location yet")
            return values
        values['zone_found'] = True
        values['area'] = values['area'] or zone.name
        settings = self.env['store.settings'].sudo()._find_for_website(self)
        if settings:
            promise = zone.delivery_method_id.sudo()._get_delivery_promise(settings)
            values['message'] = promise['message'] or values['message']
        return values

    def _geo_address_initial_point(self, partner_sudo):
        """Address map (website_delivery_geolocation): a new address, or the blank
        address of a customer who just signed up, starts from the location set
        on entry, so the location becomes the first address."""
        point = super()._geo_address_initial_point(partner_sudo)
        if point or not self.journey_enabled or (partner_sudo and partner_sudo.street):
            return point
        return self._journey_session_point()
