# -*- coding: utf-8 -*-
import pytz
import logging
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _float_to_time_str(float_time):
    try:
        hours = int(float_time)
        minutes = round((float_time - hours) * 60)
        if minutes == 60:
            hours += 1
            minutes = 0
        period = 'AM' if hours < 12 else 'PM'
        display_hour = hours % 12 or 12
        return f'{display_hour}:{minutes:02d} {period}'
    except Exception as e:
        _logger.error(f"Error converting float time {float_time}: {e}")
        return "9:00 AM"


def _next_working_day(from_date, store_settings):
    try:
        day_fields = [
            'shop_monday', 'shop_tuesday', 'shop_wednesday',
            'shop_thursday', 'shop_friday', 'shop_saturday', 'shop_sunday',
        ]
        candidate = from_date
        for _ in range(14):
            weekday = candidate.weekday()
            if getattr(store_settings, day_fields[weekday], False):
                return candidate
            candidate += timedelta(days=1)
        return from_date + timedelta(days=1)
    except Exception as e:
        _logger.error(f"Error finding next working day: {e}")
        return from_date + timedelta(days=1)


def _get_day_word(today, delivery_date):
    try:
        if delivery_date == today:
            return "today"
        elif delivery_date == today + timedelta(days=1):
            return "tomorrow"
        return delivery_date.strftime('%A')
    except Exception as e:
        _logger.error(f"Error getting day word: {e}")
        return "soon"


def _substitute_placeholders(template, opening_str, day_word):
    if not template:
        return ''
    return (
        template
        .replace('{opening_time}', opening_str)
        .replace('{day}', day_word)
    )


def _get_store_settings(website_id):
    try:
        env = request.env['store.settings'].sudo()
        settings = env.search([('website_id', '=', website_id)], limit=1)
        if not settings:
            settings = env.search([], limit=1)
        return settings
    except Exception as e:
        _logger.error(f"Error fetching store settings: {e}")
        return None


class DeliveryTimingController(http.Controller):

    @http.route('/shop/delivery/timing', type='json', auth='public', website=True)
    def get_delivery_timing(self, carrier_id=None, address_id=None, **kwargs):
        try:
            _logger.info(
                f"Delivery timing request — carrier_id: {carrier_id}, "
                f"address_id: {address_id}"
            )

            if not carrier_id:
                _logger.warning("No carrier_id provided")
                return self._empty_response()

            carrier = request.env['delivery.carrier'].sudo().browse(int(carrier_id))
            if not carrier.exists():
                _logger.warning(f"Carrier {carrier_id} not found")
                return self._empty_response()

            store_settings = _get_store_settings(request.website.id)
            if not store_settings:
                _logger.error("No store settings found")
                return self._empty_response()

            tz_name = getattr(store_settings, 'timezone', None) \
                      or request.env.company.partner_id.tz \
                      or 'Asia/Dubai'
            try:
                tz = pytz.timezone(tz_name)
            except pytz.UnknownTimeZoneError:
                _logger.warning(f"Unknown timezone '{tz_name}', falling back to Asia/Dubai")
                tz = pytz.timezone('Asia/Dubai')

            now           = datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(tz)
            current_float = now.hour + now.minute / 60.0
            today         = now.date()
            weekday       = now.weekday()

            day_fields = [
                'shop_monday', 'shop_tuesday', 'shop_wednesday',
                'shop_thursday', 'shop_friday', 'shop_saturday', 'shop_sunday',
            ]

            is_working_day = getattr(store_settings, day_fields[weekday], True)
            opening        = getattr(store_settings, 'shop_opening_time', 9.0)
            closing        = getattr(store_settings, 'shop_closing_time', 18.0)
            grace          = getattr(store_settings, 'shop_scenario2_grace_hours', 2.0)
            opening_str    = _float_to_time_str(opening)

            shop_open     = is_working_day and (opening <= current_float < closing)
            after_closing = is_working_day and (closing <= current_float < closing + grace)

            scenario         = 0
            message_template = ''
            show_popup       = False
            delivery_date    = _next_working_day(today, store_settings)

            if shop_open:
                scenario         = 1
                raw_template     = getattr(carrier, 'message_scenario_1', '') or ''
                show_popup       = bool(getattr(carrier, 'show_popup_scenario_1', False))
                enable_same_day  = getattr(carrier, 'enable_same_day_delivery', False)
                delivery_date    = today if enable_same_day else _next_working_day(today, store_settings)
                day_word         = _get_day_word(today, delivery_date)
                message_template = _substitute_placeholders(raw_template, opening_str, day_word)

            elif after_closing:
                scenario         = 2
                raw_template     = getattr(carrier, 'message_scenario_2', '') or ''
                show_popup       = bool(getattr(carrier, 'show_popup_scenario_2', False))
                delivery_date    = _next_working_day(today + timedelta(days=1), store_settings)
                day_word         = _get_day_word(today, delivery_date)
                message_template = _substitute_placeholders(raw_template, opening_str, day_word)

            else:
                scenario         = 3
                raw_template     = getattr(carrier, 'message_scenario_3', '') or ''
                show_popup       = bool(getattr(carrier, 'show_popup_scenario_3', False))
                delivery_date    = _next_working_day(today, store_settings)
                day_word         = _get_day_word(today, delivery_date)
                message_template = _substitute_placeholders(raw_template, opening_str, day_word)

            lead = max(0, int(getattr(carrier, 'lead_time_days', 0) or 0))
            if lead:
                delivery_date = _next_working_day(
                    delivery_date + timedelta(days=lead), store_settings
                )

            result = {
                'scenario':      scenario,
                'show_message':  bool(message_template),
                'show_popup':    show_popup,
                'message':       message_template,
                'delivery_date': delivery_date.strftime('%A, %B %d, %Y'),
                'opening_time':  opening_str,
                'address_id':    address_id,
            }

            _logger.info(
                f"Delivery timing response: scenario={scenario}, "
                f"show_popup={result['show_popup']}, "
                f"date={result['delivery_date']}, "
                f"message='{message_template}'"
            )
            return result

        except Exception as e:
            _logger.exception(f"Error in get_delivery_timing: {e}")
            return self._empty_response()

    @http.route('/shop/save_delivery_timing', type='json', auth='public', website=True)
    def save_delivery_timing(self, delivery_data=None, **kwargs):
        try:
            _logger.info(f"Saving delivery timing: {delivery_data}")

            if not delivery_data:
                return {'success': False, 'error': 'No delivery data provided'}

            order = request.website.sale_get_order()
            if not order:
                return {'success': False, 'error': 'No active order found'}

            values = {}
            delivery_date_str = delivery_data.get('delivery_date', '')
            if delivery_date_str:
                try:
                    parsed_date = datetime.strptime(
                        delivery_date_str, '%A, %B %d, %Y'
                    ).date()
                    values['commitment_date'] = datetime.combine(
                        parsed_date,
                        datetime.min.time().replace(hour=12)
                    )
                    _logger.info(f"Parsed commitment_date: {parsed_date}")
                except Exception as e:
                    _logger.error(f"Error parsing date '{delivery_date_str}': {e}")

            if not values:
                return {'success': False, 'error': 'Nothing to save'}

            order.sudo().write(values)
            _logger.info(f"Saved commitment_date to order {order.id}")

            return {
                'success':      True,
                'order_id':     order.id,
                'values_saved': {k: str(v) for k, v in values.items()},
            }

        except Exception as e:
            _logger.exception(f"Error in save_delivery_timing: {e}")
            return {'success': False, 'error': str(e)}

    def _empty_response(self):
        return {
            'scenario':      0,
            'show_message':  False,
            'show_popup':    False,
            'delivery_date': None,
            'opening_time':  '',
            'message':       '',
        }