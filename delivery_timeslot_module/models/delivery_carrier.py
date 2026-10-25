# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import format_date

PROMISE_TYPES = [
    ('same_day', 'Same Day'),
    ('next_day', 'Next Working Day'),
    ('early_morning', 'Before Opening'),
]
# Scenario number (kept for the website script) -> promise type
SCENARIO_TYPES = {1: 'same_day', 2: 'next_day', 3: 'early_morning'}


def float_to_time_str(float_time):
    """12.5 -> '12:30 PM'"""
    hours = int(float_time)
    minutes = round((float_time - hours) * 60)
    if minutes == 60:
        hours += 1
        minutes = 0
    hours %= 24
    period = 'AM' if hours < 12 else 'PM'
    return f'{hours % 12 or 12}:{minutes:02d} {period}'


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    # ─── Same day (Scenario 1) ─────────────────────────────────────────────────
    enable_same_day_delivery = fields.Boolean(
        string='Enable Same-Day Delivery',
        default=False,
    )
    promise_same_day_cutoff = fields.Float(
        string='Last Same-Day Order Time',
        default=19.0,
        help='Orders placed after this time (on a working day) are promised for '
             'the next working day (Scenario 2). Example: 19:00 for Abu Dhabi, '
             '21:00 for store pickup.',
    )
    promise_same_day_hours = fields.Float(
        string='Same Day: Within (hours)',
        default=3.0,
        help='Same-day promise: order time + this number of hours.',
    )

    # ─── Next working day (Scenario 2) ─────────────────────────────────────────
    promise_next_day_from = fields.Float(
        string='Next Day: From',
        default=12.0,
        help='Start of the promised window on the next working day '
             '(e.g. 12:00 for "afternoon", 10:00 for pickup).',
    )
    promise_next_day_until = fields.Float(
        string='Next Day: Until',
        default=22.0,
        help='End of the promised window: the order is on time if delivered '
             'before this time (e.g. 22:00 closing for "afternoon").',
    )

    # ─── Before opening (Scenario 3) ───────────────────────────────────────────
    promise_early_from = fields.Float(
        string='Early Morning: From',
        default=12.0,
        help='Orders placed before opening are promised later the same day, '
             'from this time...',
    )
    promise_early_until = fields.Float(
        string='Early Morning: Until',
        default=22.0,
        help='...until this time (e.g. 12:00 for "today by 12:00 PM").',
    )

    # ─── Messages ──────────────────────────────────────────────────────────────
    # Placeholders: {day} (today / tomorrow / weekday), {from}, {until}, {opening_time}
    message_scenario_1 = fields.Text(
        string='Message: Same Day (Scenario 1)',
        default='Delivered today within 3 hours',
    )
    show_popup_scenario_1 = fields.Boolean(
        string='Popup: Same Day',
        default=True,
    )
    message_scenario_2 = fields.Text(
        string='Message: Next Working Day (Scenario 2)',
        default='Your order will be delivered {day} afternoon',
    )
    show_popup_scenario_2 = fields.Boolean(
        string='Popup: Next Working Day',
        default=True,
    )
    message_scenario_3 = fields.Text(
        string='Message: Before Opening (Scenario 3)',
        default='Your order will be delivered this afternoon',
    )
    show_popup_scenario_3 = fields.Boolean(
        string='Popup: Before Opening',
        default=True,
    )

    @api.constrains(
        'promise_same_day_cutoff', 'promise_same_day_hours',
        'promise_next_day_from', 'promise_next_day_until',
        'promise_early_from', 'promise_early_until',
    )
    def _check_delivery_promise_times(self):
        for carrier in self:
            times = (
                carrier.promise_same_day_cutoff,
                carrier.promise_next_day_from, carrier.promise_next_day_until,
                carrier.promise_early_from, carrier.promise_early_until,
            )
            if any(t < 0 or t > 24 for t in times) or carrier.promise_same_day_hours < 0:
                raise ValidationError(_("Delivery promise times must be between 00:00 and 24:00."))
            if carrier.promise_next_day_from > carrier.promise_next_day_until \
                    or carrier.promise_early_from > carrier.promise_early_until:
                raise ValidationError(_("A delivery promise window must start before it ends."))

    def _get_delivery_promise(self, store_settings, now=None):
        """Delivery promise of this method for an order placed at `now`.

        Scenario 1 - same day: a working day, between opening and the last
            same-day order time (only if same-day delivery is enabled).
            Promised: order time + "Same Day: Within (hours)".
        Scenario 2 - next working day: after the last same-day order time, any
            time of the day without same-day delivery, or a closed day.
            Promised: the "Next Day" window of the next working day.
        Scenario 3 - before opening on a working day.
            Promised: the "Early Morning" window of today.

        :param store_settings: store.settings record (hours, working days, timezone)
        :param datetime now: order time, naive UTC (default: now)
        :return: dict: scenario, promise_type, message, show_popup,
            promised_from / promised_until (naive UTC), delivery_date (text),
            opening_time (text)
        """
        self.ensure_one()
        tz = store_settings._get_timezone()
        now = now or fields.Datetime.now()
        local_now = pytz.utc.localize(now).astimezone(tz)
        today = local_now.date()
        current = local_now.hour + local_now.minute / 60.0
        opening = store_settings.shop_opening_time
        cutoff = self.promise_same_day_cutoff or store_settings.shop_closing_time
        is_working_day = store_settings._is_working_day(today)

        def local_to_utc(day, float_time):
            local = tz.localize(datetime.combine(day, time.min) + timedelta(hours=float_time))
            return local.astimezone(pytz.utc).replace(tzinfo=None)

        if is_working_day and current < opening:
            scenario, day = 3, today
            window = (self.promise_early_from, self.promise_early_until)
        elif is_working_day and self.enable_same_day_delivery and current < cutoff:
            scenario, day = 1, today
            window = None
        else:
            scenario = 2
            day = store_settings._next_working_day(today + timedelta(days=1))
            window = (self.promise_next_day_from, self.promise_next_day_until)

        if window:
            promised_from, promised_until = (local_to_utc(day, t) for t in window)
            from_str, until_str = (float_to_time_str(t) for t in window)
        else:
            promised_from = now
            promised_until = now + timedelta(hours=self.promise_same_day_hours)
            local_until = pytz.utc.localize(promised_until).astimezone(tz)
            from_str = float_to_time_str(current)
            until_str = float_to_time_str(local_until.hour + local_until.minute / 60.0)

        if day == today:
            day_word = _("today")
        elif day == today + timedelta(days=1):
            day_word = _("tomorrow")
        else:
            day_word = _("on %s", day.strftime('%A'))
        opening_str = float_to_time_str(opening)
        template = self[f'message_scenario_{scenario}'] or ''
        message = (
            template
            .replace('{day}', day_word)
            .replace('{from}', from_str)
            .replace('{until}', until_str)
            .replace('{opening_time}', opening_str)
        )
        local_until_date = pytz.utc.localize(promised_until).astimezone(tz).date()
        return {
            'scenario': scenario,
            'promise_type': SCENARIO_TYPES[scenario],
            'message': message,
            'show_popup': bool(self[f'show_popup_scenario_{scenario}']),
            'promised_from': promised_from,
            'promised_until': promised_until,
            'delivery_date': local_until_date.strftime('%A, %B %d, %Y'),
            'date_label': self._promise_date_label(local_until_date, window, from_str, until_str),
            'opening_time': opening_str,
        }

    @api.model
    def _promise_date_label(self, day, window, from_str, until_str):
        """Date and time of the promise, shown under its message:
        'Wed 21 Oct · by 4:30 PM' (same day), 'Thu 22 Oct · 12:00 PM – 10:00 PM'
        (a window) or 'Thu 22 Oct · from 10:00 AM' (pickup at a set time)."""
        date_str = format_date(self.env, day, date_format='EEE d MMM')
        if not window:
            times = _("by %s", until_str)
        elif window[0] == window[1]:
            times = _("from %s", from_str)
        else:
            times = '%s – %s' % (from_str, until_str)
        return '%s · %s' % (date_str, times)
