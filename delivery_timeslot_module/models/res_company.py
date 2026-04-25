# -*- coding: utf-8 -*-
from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ─── Operating Hours ───────────────────────────────────────────────────────

    shop_opening_time = fields.Float(
        string='Opening Time',
        default=9.0,
        help='Shop opening time in 24h format. Example: 9.0 = 9:00 AM, 9.5 = 9:30 AM'
    )

    shop_closing_time = fields.Float(
        string='Closing Time',
        default=22.0,
        help='Shop closing time in 24h format. Example: 22.0 = 10:00 PM'
    )

    # ─── Operating Days ────────────────────────────────────────────────────────

    shop_monday = fields.Boolean(string='Monday', default=True)
    shop_tuesday = fields.Boolean(string='Tuesday', default=True)
    shop_wednesday = fields.Boolean(string='Wednesday', default=True)
    shop_thursday = fields.Boolean(string='Thursday', default=True)
    shop_friday = fields.Boolean(string='Friday', default=True)
    shop_saturday = fields.Boolean(string='Saturday', default=True)
    shop_sunday = fields.Boolean(string='Sunday', default=True)

    # ─── Off-Hours Threshold ───────────────────────────────────────────────────
    # This controls the boundary between Scenario 2 and Scenario 3.
    # The BRD defines:
    #   Scenario 2: "shortly after closing" → 1–2 hrs after close → "Tomorrow" message
    #   Scenario 3: "late off-hours / after midnight" → "Today by opening time" message
    #
    # We implement this as:
    #   If (current_time > closing_time) AND (current_time <= closing_time + grace_hours)
    #       → Scenario 2 (still considered "same evening", deliver tomorrow)
    #   If (current_time > closing_time + grace_hours) OR (current_time < opening_time)
    #       → Scenario 3 (deep night / early morning, deliver today by opening)

    shop_scenario2_grace_hours = fields.Float(
        string='After-Close Grace Period (hours)',
        default=2.0,
        help=(
            'Hours after closing time that still trigger the "tomorrow delivery" message '
            '(Scenario 2). Orders placed after this window trigger the "today by opening" '
            'message (Scenario 3).\n\n'
            'Example with close=22:00 and grace=2.0:\n'
            '  22:01–24:00 → Scenario 2 (tomorrow)\n'
            '  00:01–09:00 → Scenario 3 (today by 9 AM)\n'
            'BRD default: 2 hours'
        )
    )
