# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class MapAddressController(http.Controller):

    @http.route('/shop/address/map_update', type='json', auth='public', website=True)
    def map_address_update(self, **kw):
        """
        Handle map location selection and save to session/partner

        Parameters:
            latitude (float): Latitude coordinate
            longitude (float): Longitude coordinate
            street (str): Street address
            street2 (str): Additional street info
            city (str): City name
            zip (str): Postal code
            country_code (str): Country code (e.g., 'AE')
            full_address (str): Complete geocoded address
        """
        try:
            # Get parameters
            latitude = kw.get('latitude')
            longitude = kw.get('longitude')
            street = kw.get('street', '')
            street2 = kw.get('street2', '')
            city = kw.get('city', '')
            zip_code = kw.get('zip', '')
            country_code = kw.get('country_code', '')
            full_address = kw.get('full_address', '')

            _logger.info("Map location selected: lat=%s, lng=%s, address=%s",
                         latitude, longitude, full_address)

            # Store in session for checkout process
            request.session['map_latitude'] = latitude
            request.session['map_longitude'] = longitude
            request.session['map_full_address'] = full_address

            # If user is logged in, we could also update their partner address
            # This is optional - you might want to do this only on order confirmation
            if request.env.user and request.env.user != request.env.ref('base.public_user'):
                partner = request.env.user.partner_id

                # Find country
                country = None
                if country_code:
                    country = request.env['res.country'].sudo().search([
                        ('code', '=', country_code)
                    ], limit=1)

                # Prepare address values
                address_vals = {
                    'street': street,
                    'street2': street2,
                    'city': city,
                    'zip': zip_code,
                }

                if country:
                    address_vals['country_id'] = country.id

                # You can either update existing address or create new delivery address
                # For now, we'll just store in session and let the normal checkout handle it

            return {
                'success': True,
                'message': 'Location saved successfully',
                'coordinates': {
                    'lat': latitude,
                    'lng': longitude
                }
            }

        except Exception as e:
            _logger.error("Error saving map location: %s", str(e))
            return {
                'success': False,
                'error': str(e)
            }