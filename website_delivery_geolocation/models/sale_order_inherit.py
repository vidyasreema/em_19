from odoo import models, fields, api
from math import radians, cos, sin, asin, sqrt
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    delivery_distance_km = fields.Float(
        string="Delivery Distance (KM)",
        readonly=True
    )
    order_note = fields.Text(
        string='Order Notes',
        help='Special instructions or notes from the customer.'
    )

    def calculate_distance_km(self, lat1, lon1, lat2, lon2):
        """Haversine formula to calculate distance in KM"""
        if not all([lat1, lon1, lat2, lon2]):
            _logger.warning("Missing latitude/longitude for distance calculation")
            return 0.0

        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))
        return round(6371 * c, 2)

    def get_delivery_method_for_location(self):
        """
        Get delivery method for a location - returns False if no zone found
        IMPORTANT: This now checks EXCLUSION zones too!
        """
        self.ensure_one()

        if not self.partner_shipping_id:
            _logger.warning("Order %s has no shipping partner", self.name)
            return False

        latitude = self.partner_shipping_id.partner_latitude
        longitude = self.partner_shipping_id.partner_longitude

        if not latitude or not longitude:
            _logger.warning(
                "Partner %s (ID: %s) has no coordinates",
                self.partner_shipping_id.name,
                self.partner_shipping_id.id
            )
            return False

        _logger.info(
            "🔍 Checking delivery zones for order %s at coordinates (%s, %s)",
            self.name, latitude, longitude
        )

        zones = self.env['delivery.zone'].search([
            ('active', '=', True),
            ('polygon', '!=', False)
        ])

        if not zones:
            _logger.warning("⚠️ No active delivery zones configured in system")
            return False

        _logger.info("📍 Checking %s delivery zone(s)", len(zones))

        for zone in zones:
            # This now checks both inclusion AND exclusion zones!
            if zone.is_location_in_zone(latitude, longitude):
                _logger.info(
                    "✅ Location (%s, %s) matched zone: %s (Method: %s)",
                    latitude, longitude, zone.name,
                    zone.delivery_method_id.name if zone.delivery_method_id else 'None'
                )

                if not zone.delivery_method_id:
                    _logger.warning(
                        "⚠️ Zone %s has no delivery method configured",
                        zone.name
                    )
                    continue

                return zone.delivery_method_id

        _logger.warning(
            "🚫 No delivery zone found for location (%s, %s) - Either outside all zones or in exclusion area",
            latitude, longitude
        )
        return False

    def _get_delivery_methods(self):
        """Override to filter delivery methods by zone"""
        self.ensure_one()

        # Get the zone-based delivery method
        zone_delivery_method = self.get_delivery_method_for_location()

        if not zone_delivery_method:
            # NO ZONE FOUND - Return empty list to block checkout
            _logger.warning(
                "🚫 No delivery available for order %s - Location not in any delivery zone",
                self.name
            )
            return self.env['delivery.carrier']  # Empty recordset

        # Zone found - return ONLY the zone's delivery method
        # This ensures users can only select the correct method for their location
        _logger.info(
            "✅ Delivery method available for order %s: %s",
            self.name,
            zone_delivery_method.name
        )

        # Auto-select if not already selected
        if self.carrier_id != zone_delivery_method:
            try:
                self._set_delivery_method(zone_delivery_method)
                _logger.info(
                    "✅ Auto-selected delivery method %s for order %s",
                    zone_delivery_method.name,
                    self.name
                )
            except Exception as e:
                _logger.warning(
                    "⚠️ Could not auto-select delivery method: %s", e
                )

        # Return only the zone-specific delivery method
        # This prevents users from selecting wrong methods
        return zone_delivery_method

    @api.model
    def create(self, vals):
        """Create order and auto-assign delivery method based on location"""
        order = super().create(vals)

        if order.partner_shipping_id:
            _logger.info(
                "🆕 New order %s created for partner %s",
                order.name,
                order.partner_shipping_id.name
            )
            method = order.get_delivery_method_for_location()
            if method:
                order._set_delivery_method(method)
            else:
                _logger.warning(
                    "⚠️ Order %s created but no delivery zone found for location",
                    order.name
                )

        return order

    def write(self, vals):
        """Update delivery method when address changes"""
        res = super().write(vals)

        # Recompute if partner or coordinates changed
        if 'partner_shipping_id' in vals or 'partner_id' in vals:
            for order in self:
                if order.state not in ['draft', 'sent']:
                    # Don't change delivery for confirmed orders
                    _logger.info(
                        "ℹ️ Order %s is %s - skipping delivery method update",
                        order.name,
                        order.state
                    )
                    continue

                if order.partner_shipping_id:
                    _logger.info(
                        "🔄 Address changed for order %s - rechecking delivery zones",
                        order.name
                    )
                    method = order.get_delivery_method_for_location()
                    if method:
                        if order.carrier_id != method:
                            order._set_delivery_method(method)
                            _logger.info(
                                "✅ Updated delivery method to %s for order %s",
                                method.name,
                                order.name
                            )
                    else:
                        # Clear delivery method if no zone found
                        if order.carrier_id:
                            _logger.warning(
                                "⚠️ Clearing delivery method for order %s - no zone found",
                                order.name
                            )
                            order.carrier_id = False

        return res

    def action_check_delivery_zone(self):
        """
        Manual action to check delivery zone coverage
        Can be called from a button in the UI
        """
        self.ensure_one()

        if not self.partner_shipping_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Shipping Address',
                    'message': 'Please set a shipping address first',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        latitude = self.partner_shipping_id.partner_latitude
        longitude = self.partner_shipping_id.partner_longitude

        if not latitude or not longitude:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Coordinates',
                    'message': f'Address "{self.partner_shipping_id.name}" has no GPS coordinates',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        method = self.get_delivery_method_for_location()

        if method:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '✅ Delivery Available',
                    'message': f'This location is covered by: {method.name}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '🚫 No Delivery',
                    'message': f'This location ({latitude}, {longitude}) is not in any delivery zone',
                    'type': 'danger',
                    'sticky': True,
                }
            }