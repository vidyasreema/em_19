# -*- coding: utf-8 -*-
from odoo import models, fields


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    enable_same_day_delivery = fields.Boolean(
        string='Enable Same-Day Delivery',
        default=False,
    )

    lead_time_days = fields.Integer(
        string='Minimum Lead Time (Days)',
        default=1,
    )

    # Scenario 1
    message_scenario_1 = fields.Text(
        string='Message: Within Working Hours (Scenario 1)',
        placeholder='Leave empty for no message',
    )
    show_popup_scenario_1 = fields.Boolean(
        string='Show Warning Popup',
        default=True,
    )

    # Scenario 2
    message_scenario_2 = fields.Text(
        string='Message: Shortly After Closing (Scenario 2)',
        default='Your order will be ready for delivery tomorrow during working hours.',
    )
    show_popup_scenario_2 = fields.Boolean(
        string='Show Warning Popup',
        default=True,
    )

    # Scenario 3
    message_scenario_3 = fields.Text(
        string='Message: Late Night / Early Morning (Scenario 3)',
        default='Your order will be available for delivery today by {opening_time}.',
    )
    show_popup_scenario_3 = fields.Boolean(
        string='Show Warning Popup',
        default=True,
    )