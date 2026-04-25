from odoo import models, fields
import json
import logging

_logger = logging.getLogger(__name__)


class DeliveryZone(models.Model):
    _name = "delivery.zone"
    _description = "Delivery Zone"

    name = fields.Char(string="Zone Name", required=True)
    code = fields.Char(string="Zone Code")
    polygon = fields.Text(string="Zone Area")
    delivery_method_id = fields.Many2one(
        'delivery.carrier',
        string='Delivery Method',
        domain=[('website_published', '=', True)]
    )
    active = fields.Boolean(default=True)

    def is_location_in_zone(self, latitude, longitude):
        """Check if a point is inside this zone's inclusion area but NOT in exclusion areas"""
        self.ensure_one()

        if not self.polygon:
            return False

        try:
            zone_data = json.loads(self.polygon)

            # Check if point is in the main inclusion zone
            inclusion_zone = zone_data.get('inclusion')
            if not inclusion_zone:
                _logger.warning(f"Zone {self.name} has no inclusion area defined")
                return False

            if inclusion_zone.get('type') != 'Polygon':
                _logger.warning(f"Zone {self.name} inclusion area is not a Polygon")
                return False

            inclusion_coords = inclusion_zone['coordinates'][0]
            is_in_target = self._point_inside_polygon(longitude, latitude, inclusion_coords)

            # If not in target area, no need to check exclusions
            if not is_in_target:
                _logger.info(f"Point ({latitude}, {longitude}) is NOT in inclusion zone for {self.name}")
                return False

            # Check if point is in any exclusion zone
            exclusion_zones = zone_data.get('exclusions', [])
            for exclusion in exclusion_zones:
                if exclusion.get('type') == 'Polygon':
                    exclusion_coords = exclusion['coordinates'][0]
                    if self._point_inside_polygon(longitude, latitude, exclusion_coords):
                        _logger.info(f"Point ({latitude}, {longitude}) is in exclusion zone for {self.name}")
                        return False

            _logger.info(f"Point ({latitude}, {longitude}) IS in delivery zone for {self.name}")
            return True

        except Exception as e:
            _logger.error(f"Error checking zone {self.name}: {e}")
            return False

    def _point_inside_polygon(self, x, y, polygon):
        """
        Ray-casting algorithm for point-in-polygon check.
        x = longitude, y = latitude
        polygon = list of [longitude, latitude] pairs (GeoJSON format)
        """
        n = len(polygon)
        inside = False
        p1x, p1y = polygon[0]

        for i in range(1, n + 1):
            p2x, p2y = polygon[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                            if p1x == p2x or x <= xinters:  # ✅ FIXED: inside p1y != p2y block
                                inside = not inside
            p1x, p1y = p2x, p2y

        return inside

    def get_zone_info(self):
        """Helper method to get zone statistics"""
        self.ensure_one()

        if not self.polygon:
            return {
                'has_inclusion': False,
                'exclusion_count': 0
            }

        try:
            zone_data = json.loads(self.polygon)
            return {
                'has_inclusion': bool(zone_data.get('inclusion')),
                'exclusion_count': len(zone_data.get('exclusions', []))
            }
        except:
            return {
                'has_inclusion': False,
                'exclusion_count': 0
            }

class Website(models.Model):
    _inherit = 'website'

    def _display_partner_b2b_fields(self):
        return False