from datetime import datetime, timedelta

from odoo.tests import tagged

from odoo.addons.delivery_timeslot_module.controllers.main import PaymentPortalDeliveryPromise
from odoo.addons.website_sale.tests.common import MockRequest, WebsiteSaleCommon


def dubai(day, hour, minute=0):
    """Local Dubai time (UTC+4) of October 2026 as naive UTC.
    21/10/2026 is a Wednesday."""
    return datetime(2026, 10, day, hour, minute) - timedelta(hours=4)


@tagged('post_install', '-at_install')
class TestDeliveryPromise(WebsiteSaleCommon):
    """Annex 3, section 8: messages, popups and promised times per delivery method."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website.company_id.partner_id.tz = 'Asia/Dubai'
        cls.settings = cls.env['store.settings'].get_store_settings(cls.website.id)
        cls.settings.write({'shop_opening_time': 9.0, 'shop_closing_time': 22.0})
        product = cls._prepare_carrier_product()
        cls.island = cls._prepare_carrier(product, name="Abu Dhabi Island delivery", **{
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
        })
        cls.emirates = cls._prepare_carrier(product, name="Delivery Fee", **{
            'enable_same_day_delivery': False,
            'promise_next_day_from': 12.0,
            'promise_next_day_until': 22.0,
            'promise_early_from': 12.0,
            'promise_early_until': 22.0,
            'message_scenario_2': 'Your order will be delivered {day} afternoon',
            'show_popup_scenario_2': True,
            'message_scenario_3': 'Your order will be delivered this afternoon',
            'show_popup_scenario_3': True,
        })
        cls.pickup = cls._prepare_carrier(product, name="Pick up in store", **{
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
        })

    def assertPromise(self, carrier, now, scenario, message, popup, until, start=None):
        promise = carrier._get_delivery_promise(self.settings, now=now)
        self.assertEqual(promise['scenario'], scenario)
        self.assertEqual(promise['message'], message)
        self.assertEqual(promise['show_popup'], popup)
        self.assertEqual(promise['promised_until'], until)
        if start:
            self.assertEqual(promise['promised_from'], start)
        return promise

    # ── Island and OAD ────────────────────────────────────────────
    def test_island_1830_same_day(self):
        promise = self.assertPromise(
            self.island, dubai(21, 18, 30), 1, 'Delivered today within 3 hours', True,
            until=dubai(21, 21, 30))
        self.assertEqual(promise['promise_type'], 'same_day')

    def test_island_2000_tomorrow_afternoon(self):
        promise = self.assertPromise(
            self.island, dubai(21, 20), 2, 'Your order will be delivered tomorrow afternoon', True,
            until=dubai(22, 22), start=dubai(22, 12))
        self.assertEqual(promise['promise_type'], 'next_day')

    def test_island_0100_today_by_noon(self):
        promise = self.assertPromise(
            self.island, dubai(21, 1), 3, 'Your order will be delivered today by 12:00 PM', True,
            until=dubai(21, 12))
        self.assertEqual(promise['promise_type'], 'early_morning')

    def test_island_cutoff_is_exclusive(self):
        self.assertPromise(
            self.island, dubai(21, 19), 2, 'Your order will be delivered tomorrow afternoon', True,
            until=dubai(22, 22))

    # ── Other Emirates (Dubai) ────────────────────────────────────
    def test_emirates_daytime_tomorrow_afternoon(self):
        self.assertPromise(
            self.emirates, dubai(21, 10), 2, 'Your order will be delivered tomorrow afternoon', True,
            until=dubai(22, 22), start=dubai(22, 12))

    def test_emirates_0100_this_afternoon(self):
        self.assertPromise(
            self.emirates, dubai(21, 1), 3, 'Your order will be delivered this afternoon', True,
            until=dubai(21, 22), start=dubai(21, 12))

    # ── Store pickup ──────────────────────────────────────────────
    def test_pickup_2030_within_one_hour(self):
        self.assertPromise(
            self.pickup, dubai(21, 20, 30), 1, 'Ready for pickup within 1 hour', True,
            until=dubai(21, 21, 30))

    def test_pickup_2130_tomorrow_10am(self):
        self.assertPromise(
            self.pickup, dubai(21, 21, 30), 2, 'Ready for pickup tomorrow from 10:00 AM', True,
            until=dubai(22, 10))

    def test_pickup_0100_today_10am(self):
        self.assertPromise(
            self.pickup, dubai(21, 1), 3, 'Ready for pickup today from 10:00 AM', True,
            until=dubai(21, 10))

    # ── Closed days ───────────────────────────────────────────────
    def test_next_day_skips_closed_day(self):
        self.settings.shop_thursday = False
        self.assertPromise(
            self.island, dubai(21, 20), 2, 'Your order will be delivered on Friday afternoon', True,
            until=dubai(23, 22))

    def test_closed_today_is_next_working_day(self):
        self.settings.shop_wednesday = False
        self.assertPromise(
            self.island, dubai(21, 10), 2, 'Your order will be delivered tomorrow afternoon', True,
            until=dubai(22, 22))
        self.assertPromise(
            self.island, dubai(21, 1), 2, 'Your order will be delivered tomorrow afternoon', True,
            until=dubai(22, 22))

    # ── Saved on the order ────────────────────────────────────────
    def test_promise_saved_on_order(self):
        self.cart.carrier_id = self.island
        self.cart._store_delivery_promise(now=dubai(21, 20))
        self.assertEqual(self.cart.delivery_promise_type, 'next_day')
        self.assertEqual(self.cart.delivery_promise_message, 'Your order will be delivered tomorrow afternoon')
        self.assertEqual(self.cart.delivery_promise_from, dubai(22, 12))
        self.assertEqual(self.cart.delivery_promise_until, dubai(22, 22))
        self.assertEqual(self.cart.commitment_date, dubai(22, 22))

    def test_promise_saved_when_customer_pays(self):
        self.cart.carrier_id = self.pickup
        with MockRequest(self.env, website=self.website, sale_order_id=self.cart.id):
            PaymentPortalDeliveryPromise()._validate_transaction_for_order(None, self.cart)
        self.assertTrue(self.cart.delivery_promise_until)
        self.assertEqual(self.cart.commitment_date, self.cart.delivery_promise_until)

    def test_promise_saved_on_confirmation(self):
        self.cart.carrier_id = self.island
        self.cart.action_confirm()
        self.assertTrue(self.cart.delivery_promise_until)
        self.assertEqual(self.cart.commitment_date, self.cart.delivery_promise_until)

    def test_order_without_delivery_method(self):
        self.assertFalse(self.cart.carrier_id)
        self.cart._store_delivery_promise()
        self.assertFalse(self.cart.delivery_promise_until)
        self.assertFalse(self.cart.commitment_date)

    # ── Date line under the message ───────────────────────────────
    def test_date_label(self):
        def label(carrier, now):
            return carrier._get_delivery_promise(self.settings, now=now)['date_label']
        self.assertEqual(label(self.island, dubai(21, 18, 30)), 'Wed 21 Oct · by 9:30 PM', "same day: order + 3 h")
        self.assertEqual(label(self.island, dubai(21, 20)), 'Thu 22 Oct · 12:00 PM – 10:00 PM', "tomorrow afternoon")
        self.assertEqual(label(self.island, dubai(21, 1)), 'Wed 21 Oct · 9:00 AM – 12:00 PM', "today by 12:00 PM")
        self.assertEqual(label(self.pickup, dubai(21, 21, 30)), 'Thu 22 Oct · from 10:00 AM', "pickup at a set time")

    def test_date_label_on_order(self):
        self.cart.carrier_id = self.island
        self.cart._store_delivery_promise(now=dubai(21, 20))
        self.assertEqual(self.cart.delivery_promise_date_label, 'Thu 22 Oct · 12:00 PM – 10:00 PM')
        self.cart._store_delivery_promise(now=dubai(21, 18, 30))
        self.assertEqual(self.cart.delivery_promise_date_label, 'Wed 21 Oct · by 9:30 PM')

    def test_promise_in_confirmation_email(self):
        template = self.env.ref('sale.mail_template_sale_confirmation')
        Template = self.env['mail.template']
        Template._timeslot_add_promise_to_confirmation_email()
        Template._timeslot_add_promise_to_confirmation_email()
        self.assertEqual(template.body_html.count('o_delivery_promise_block'), 1, "added once")
        self.assertNotIn('&lt;div class="o_delivery_promise_block"', str(template.body_html), "HTML, not escaped text")
        self.cart.carrier_id = self.island
        self.cart._store_delivery_promise(now=dubai(21, 20))
        body = template._render_field('body_html', self.cart.ids)[self.cart.id]
        self.assertIn('Your order will be delivered tomorrow afternoon', body)
        self.assertIn('Thu 22 Oct · 12:00 PM – 10:00 PM', body)

    def test_promise_in_older_email_version(self):
        """Older template versions (like a translated copy) start "Ship to" differently."""
        template = self.env['mail.template'].create({
            'name': 'Old confirmation', 'model_id': self.env.ref('sale.model_sale_order').id,
            'body_html': '<div><p>Hello</p><div t-if="object.partner_shipping_id and not object.only_services">Ship to</div></div>',
        })
        self.env['ir.config_parameter'].sudo().set_param('sale.default_confirmation_template', str(template.id))
        self.env['mail.template']._timeslot_add_promise_to_confirmation_email()
        body = str(template.body_html)
        self.assertEqual(body.count('o_delivery_promise_block'), 1)
        self.assertLess(body.index('o_delivery_promise_block'), body.index('Ship to'), "above Ship to")
