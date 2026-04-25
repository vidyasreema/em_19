# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale
import logging

_logger = logging.getLogger(__name__)


class WebsiteSaleCoordinates(WebsiteSale):

    def _checkout_form_save(self, mode, checkout, all_values):
        """
        Override to inject coordinates into partner data before saving
        This is called BEFORE partner.write() or partner.create()
        """
        _logger.info("=" * 80)
        _logger.info("🔧 _checkout_form_save intercepted!")
        _logger.info("   Mode: %s", mode)
        _logger.info("   all_values keys: %s", list(all_values.keys()))
        _logger.info("=" * 80)

        # Extract coordinates from form submission
        latitude = all_values.get('partner_latitude')
        longitude = all_values.get('partner_longitude')

        if latitude and longitude:
            try:
                lat = float(latitude)
                lng = float(longitude)

                _logger.info("📍 Found coordinates in form: lat=%s, lon=%s", lat, lng)

                # CRITICAL: Add coordinates to checkout dict
                # This dict is used to update/create the partner
                checkout['partner_latitude'] = lat
                checkout['partner_longitude'] = lng

                _logger.info("✅ Coordinates injected into checkout dict")

            except (ValueError, TypeError) as e:
                _logger.warning("⚠️ Invalid coordinate values: %s", e)
        else:
            _logger.info("ℹ️ No coordinates found in form submission")

        # Call parent method (this will create/update partner with our coordinates)
        result = super()._checkout_form_save(mode, checkout, all_values)

        _logger.info("✅ _checkout_form_save completed")
        _logger.info("=" * 80)

        return result