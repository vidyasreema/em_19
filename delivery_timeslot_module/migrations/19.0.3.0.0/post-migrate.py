import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

ABU_DHABI = {
    'enable_same_day_delivery': True,
    'promise_same_day_cutoff': 19.0,
    'promise_same_day_hours': 3.0,
    'promise_next_day_from': 12.0,
    'promise_next_day_until': 22.0,
    'promise_early_from': 9.0,
    'promise_early_until': 12.0,
    'message_scenario_1': 'Delivered today within 3 hours',
    'show_popup_scenario_1': True,
    'message_scenario_2': 'Your order will be delivered {day} afternoon',
    'show_popup_scenario_2': True,
    'message_scenario_3': 'Your order will be delivered today by {until}',
    'show_popup_scenario_3': True,
}

# Annex 3, section 8: delivery promise of each delivery method.
# Values can be changed afterwards in the "Delivery Timing" tab of each method.
PROMISES = {
    'Abu Dhabi Island delivery': ABU_DHABI,
    'Outside Abu Dhabi Island Delivery': ABU_DHABI,
    'Delivery Fee': {  # other Emirates: never same day
        'enable_same_day_delivery': False,
        'promise_next_day_from': 12.0,
        'promise_next_day_until': 22.0,
        'promise_early_from': 12.0,
        'promise_early_until': 22.0,
        'message_scenario_1': False,
        'show_popup_scenario_1': True,
        'message_scenario_2': 'Your order will be delivered {day} afternoon',
        'show_popup_scenario_2': True,
        'message_scenario_3': 'Your order will be delivered this afternoon',
        'show_popup_scenario_3': True,
    },
    'Pick up in store': {
        'enable_same_day_delivery': True,
        'promise_same_day_cutoff': 21.0,
        'promise_same_day_hours': 1.0,
        'promise_next_day_from': 10.0,
        'promise_next_day_until': 10.0,
        'promise_early_from': 10.0,
        'promise_early_until': 10.0,
        'message_scenario_1': 'Ready for pickup within 1 hour',
        'show_popup_scenario_1': True,
        'message_scenario_2': 'Ready for pickup {day} from {from}',
        'show_popup_scenario_2': True,
        'message_scenario_3': 'Ready for pickup today from {from}',
        'show_popup_scenario_3': True,
    },
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Carrier = env['delivery.carrier'].with_context(active_test=False)
    for name, values in PROMISES.items():
        carriers = Carrier.search([('name', '=', name)])
        if carriers:
            carriers.write(values)
            _logger.info("Delivery promise set on %s", carriers.mapped('name'))
        else:
            _logger.warning("Delivery method %r not found: set its Delivery Timing tab by hand", name)
