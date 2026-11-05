import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Annex 3B, section 1: how each delivery method shows on the Delivery page and the
# homepage FAQ (approved content board). Only empty values are filled; they can be
# changed afterwards in the "Website Pages" tab of each delivery method.
METHODS = {
    'Abu Dhabi Island delivery': {'cut_area': 'abu_dhabi', 'cut_website_name': 'Abu Dhabi Island'},
    'Outside Abu Dhabi Island Delivery': {
        'cut_area': 'abu_dhabi', 'cut_website_name': 'Abu Dhabi, off the island',
        'cut_website_note': 'For example Masdar City'},
    'Delivery Fee': {'cut_area': 'uae', 'cut_website_name': 'Rest of the UAE'},
    'Pick up in store': {
        'cut_area': 'pickup', 'cut_website_name': 'Pickup from our shop', 'cut_website_note': 'Mushrif Mall'},
}
# "Need to cancel?" and the footer (Annex A, task 1.4)
WHATSAPP_NUMBER = '+971 50 717 9729'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Carrier = env['delivery.carrier'].with_context(active_test=False)
    for name, values in METHODS.items():
        carriers = Carrier.search([('name', '=', name)])
        if not carriers:
            _logger.warning("Delivery method %r not found: fill its Website Pages tab by hand", name)
        for carrier in carriers:
            missing = {field: value for field, value in values.items() if not carrier[field]}
            if missing:
                carrier.write(missing)
                _logger.info("Website pages values set on %s: %s", carrier.name, missing)
    env['website'].search([('journey_whatsapp_number', '=', False)]).journey_whatsapp_number = WHATSAPP_NUMBER
