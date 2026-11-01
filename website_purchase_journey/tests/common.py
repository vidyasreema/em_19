import json

from odoo import Command
from odoo.tests import HttpCase


# A square around Abu Dhabi island centre (24.4539, 54.3773)
ABU_DHABI = {'inclusion': {'type': 'Polygon', 'coordinates': [[
    [54.30, 24.40], [54.45, 24.40], [54.45, 24.52], [54.30, 24.52], [54.30, 24.40]]]}, 'exclusions': []}


class JourneyCommon(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].get_current_website()
        cls.website.journey_enabled = True
        cls.website.journey_general_promise = 'Same-day delivery in Abu Dhabi for orders before 7:00 PM'
        if 'signup_verification' in cls.website._fields:
            # website_signup_verification (Annex 3A) has its own tests: the standard sign-up here
            cls.website.write({'signup_verification': False, 'signup_coupon_program_id': False})
        if 'my_account_page' in cls.website._fields:
            # website_my_account has its own tests: the standard My Account page here
            cls.website.my_account_page = False
        # Open all day: the same-day promise does not depend on when the tests run
        cls.env['store.settings'].get_store_settings(cls.website.id).write(
            {'shop_opening_time': 0.0, 'shop_closing_time': 24.0})

        Ribbon = cls.env['product.ribbon']
        cls.out_of_stock = Ribbon.search([('name', '=ilike', 'Out of stock')], limit=1) \
            or Ribbon.create({'name': 'Out of stock'})
        cls.sale_ribbon = Ribbon.create({'name': 'Hot deal'})

        weight = cls.env['product.attribute'].create({
            'name': 'Tour Weight', 'create_variant': 'always',
            'value_ids': [Command.create({'name': '1 kg', 'sequence': 1}),
                          Command.create({'name': '500 g', 'sequence': 2}),
                          Command.create({'name': '250 g', 'sequence': 3})],
        })
        origin = cls.env['product.attribute'].create({
            'name': 'Tour Origin', 'create_variant': 'always', 'value_ids': [Command.create({'name': 'Australian'})],
        })
        cls.multi = cls.env['product.template'].create({
            'name': 'TOUR Ribeye', 'list_price': 100.0, 'is_published': True, 'sale_ok': True,
            'type': 'consu', 'taxes_id': [Command.clear()],
            'attribute_line_ids': [
                Command.create({'attribute_id': weight.id, 'value_ids': [Command.set(weight.value_ids.ids)]}),
                Command.create({'attribute_id': origin.id, 'value_ids': [Command.set(origin.value_ids.ids)]}),
            ],
        })
        # Prices of the weights: 1 kg = 100, 500 g = 60, 250 g = 35
        extras = {'1 kg': 0.0, '500 g': -40.0, '250 g': -65.0}
        for ptav in cls.multi.attribute_line_ids[0].product_template_value_ids:
            ptav.price_extra = extras[ptav.name]
        cls.variant_250 = cls.multi.product_variant_ids.filtered(
            lambda v: '250 g' in v.product_template_attribute_value_ids.mapped('name'))

        cls.single = cls.env['product.template'].create({
            'name': 'TOUR Sausages', 'list_price': 40.0, 'is_published': True, 'sale_ok': True,
            'type': 'consu', 'taxes_id': [Command.clear()],
        })
        cls.sold_out = cls.env['product.template'].create({
            'name': 'TOUR Tomahawk', 'list_price': 300.0, 'is_published': True, 'sale_ok': True,
            'type': 'consu', 'taxes_id': [Command.clear()], 'website_ribbon_id': cls.out_of_stock.id,
        })

        product = cls.env['product.product'].create({'name': 'Delivery', 'type': 'service'})
        cls.island = cls.env['delivery.carrier'].create({
            'name': 'Island', 'product_id': product.id, 'delivery_type': 'fixed', 'fixed_price': 40.0,
            'enable_same_day_delivery': True, 'promise_same_day_cutoff': 24.0, 'promise_same_day_hours': 3.0,
            'message_scenario_1': 'Delivered today within 3 hours',
            'message_scenario_2': 'Delivered {day} afternoon',
            'message_scenario_3': 'Delivered today by {until}',
        })
        cls.zone = cls.env['delivery.zone'].create({
            'name': 'Abu Dhabi Island', 'polygon': json.dumps(ABU_DHABI), 'delivery_method_id': cls.island.id,
        })
