from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _get_frontend_writable_fields(self):
        """Allow the checkout address form to save the map pin (hidden inputs)."""
        fields_set = super()._get_frontend_writable_fields()
        fields_set.update({'partner_latitude', 'partner_longitude'})
        return fields_set

    def _geo_localize_if_address(self):
        """Geo-localize partner only when address is complete enough"""
        for partner in self:
            if partner.street and partner.city and partner.country_id:
                try:
                    _logger.info(
                        "🌍 Geo-localizing partner %s (%s, %s, %s)",
                        partner.id,
                        partner.street,
                        partner.city,
                        partner.country_id.name
                    )
                    partner.geo_localize()
                    _logger.info(
                        "✅ Partner %s geolocated: lat=%s lon=%s",
                        partner.id,
                        partner.partner_latitude,
                        partner.partner_longitude
                    )
                except Exception as e:
                    _logger.warning(
                        "⚠️ Geo localization failed for partner %s: %s", partner.id, e
                    )

    @api.model_create_multi
    def create(self, vals_list):
        """Create partner and geocode only if coordinates not provided"""
        partners = super().create(vals_list)
        for partner, vals in zip(partners, vals_list):
            has_coordinates = vals.get('partner_latitude') and vals.get('partner_longitude')
            if not has_coordinates:
                partner._geo_localize_if_address()
        return partners

    def write(self, vals):
        """Update partner - skip geocoding if coordinates exist"""
        coordinates_in_vals = (
                'partner_latitude' in vals and
                'partner_longitude' in vals
        )

        res = super().write(vals)

        if coordinates_in_vals:
            _logger.info("✅ Coordinates in vals - skipped geocoding")
            return res

        address_fields = {'street', 'street2', 'city', 'state_id', 'zip', 'country_id'}

        if address_fields.intersection(vals.keys()):
            for partner in self:
                if partner.partner_latitude and partner.partner_longitude:
                    _logger.info(
                        "✅ Partner %s already has coordinates (%.6f, %.6f) - SKIPPING geocoding",
                        partner.id,
                        partner.partner_latitude,
                        partner.partner_longitude
                    )
                    continue

                if partner.street and partner.city and partner.country_id:
                    _logger.info("🗺️ Partner %s has no coordinates - geocoding", partner.id)
                    partner._geo_localize_if_address()

        return res