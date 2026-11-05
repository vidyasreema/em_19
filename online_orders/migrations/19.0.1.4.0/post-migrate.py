import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# The shop's pickup method (Annex 3B, 5.1); can be changed on the delivery method afterwards
PICKUP_METHOD = 'Pick up in store'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Carrier = env['delivery.carrier'].with_context(active_test=False)
    if Carrier.search_count([('online_pickup', '=', True)]):
        return
    carriers = Carrier.search([('name', '=', PICKUP_METHOD)])
    if carriers:
        carriers.online_pickup = True
        _logger.info("Pickup from the Shop set on %s", carriers.mapped('name'))
    else:
        _logger.warning("Delivery method %r not found: tick Pickup from the Shop on the pickup method", PICKUP_METHOD)
