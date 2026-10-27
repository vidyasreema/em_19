from datetime import datetime, time, timedelta

import pytz

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.online_orders.models.res_partner import parse_coordinates

from .common import OnlineOrdersCommon


@tagged('post_install', '-at_install')
class TestOnlineOrderStages(OnlineOrdersCommon):
    """Annex 4, section 7: verification after delivery."""

    def test_01_new_order_in_new_stage(self):
        order = self._create_order()
        self.assertEqual(order.stage_id, self.stage_new)
        self.assertEqual(order.state, 'sale')

    def test_02_out_for_delivery_validates_delivery(self):
        order = self._tracked(self._create_order())
        picking = order.picking_ids
        self.assertNotEqual(picking.state, 'done')
        order.action_online_next_stage()
        self._flush_tracking()
        self.assertEqual(order.stage_id, self.stage_out)
        self.assertEqual(picking.state, 'done', "the delivery order is validated")
        self.assertEqual(self.meat.qty_available, -2.0, "the stock is deducted (negative, no stock)")
        self.assertTrue(order.online_out_for_delivery_date)
        self.assertTrue(self._messages_with_subject(order, 'is on the way'), "the stage email is sent")
        self.assertEqual(order.state, 'sale')

    def test_03_delivered_keeps_sale_state(self):
        order = self._tracked(self._create_order())
        order.action_online_next_stage()
        order.action_online_next_stage()
        self._flush_tracking()
        self.assertEqual(order.stage_id, self.stage_delivered)
        self.assertTrue(order.online_delivered_date)
        self.assertEqual(order.state, 'sale', "the order stays in the sales report")
        self.assertTrue(self._messages_with_subject(order, 'Thank you for your order'))
        self.assertFalse(order.online_next_stage_id, "Completed is automatic only")

    def test_04_skipping_out_for_delivery_still_validates(self):
        order = self._create_order()
        order.stage_id = self.stage_delivered
        self.assertEqual(order.picking_ids.state, 'done')
        self.assertTrue(order.online_out_for_delivery_date)
        self.assertTrue(order.online_delivered_date)

    def test_05_forbidden_moves(self):
        order = self._create_order()
        order.action_online_next_stage()
        with self.assertRaises(UserError, msg="no going back"):
            order.stage_id = self.stage_new
        with self.assertRaises(UserError, msg="Completed is automatic"):
            order.stage_id = self.stage_completed
        with self.assertRaises(UserError, msg="Cancel needs the reason dialog"):
            order.stage_id = self.stage_cancelled
        self.assertEqual(order.stage_id, self.stage_out)

    def test_06_failed_validation_does_not_move(self):
        lot_product = self.env['product.product'].create({
            'name': 'Lot meat', 'type': 'consu', 'is_storable': True, 'tracking': 'lot',
        })
        order = self._create_order(product=lot_product)
        with self.assertRaises(UserError):
            order.action_online_next_stage()
        self.assertEqual(order.stage_id, self.stage_new)
        self.assertFalse(order.online_out_for_delivery_date)

    def test_07_cron_completes_delivered_orders(self):
        delivered = self._create_order()
        delivered.stage_id = self.stage_delivered
        on_the_way = self._create_order()
        on_the_way.stage_id = self.stage_out
        self.env['sale.order']._cron_online_orders_complete()
        self.assertEqual(delivered.stage_id, self.stage_completed)
        self.assertTrue(delivered.online_completed_date)
        self.assertEqual(on_the_way.stage_id, self.stage_out)
        with self.assertRaises(UserError, msg="a completed order is closed"):
            delivered.stage_id = self.stage_delivered

    def test_08_cancel_requires_reason(self):
        order = self._create_order()
        wizard = Form(self.env['online.order.cancel.wizard'].with_context(default_order_id=order.id))
        with self.assertRaises(AssertionError):
            wizard.save()

    def test_09_cancel_with_reason(self):
        self.stage_cancelled.activity_user_id = self.manager_user
        order = self._create_order()
        order.action_online_next_stage()
        wizard = self._tracked(self.env['online.order.cancel.wizard']).with_user(self.sales_user).create({
            'order_id': order.id, 'reason': 'address', 'note': 'Customer unreachable',
        })
        wizard.action_cancel_order()
        self._flush_tracking()
        self.assertEqual(order.state, 'cancel', "the standard Cancel ran")
        self.assertEqual(order.stage_id, self.stage_cancelled)
        self.assertEqual(order.online_cancel_reason, 'address')
        self.assertTrue(order.online_cancel_date)
        self.assertTrue(self._messages_with_subject(order, 'has been cancelled'))
        activity = order.activity_ids.filtered(lambda a: a.user_id == self.manager_user)
        self.assertEqual(activity.summary, 'Refund within 48 hours', "Accounts are notified")

    def test_10_standard_cancel_moves_to_cancelled(self):
        order = self._create_order()
        order.action_cancel()
        self.assertEqual(order.stage_id, self.stage_cancelled)
        self.assertFalse(order.picking_ids.filtered(lambda p: p.state != 'cancel'))

    def test_11_new_stage_with_template_without_code(self):
        template = self.env['mail.template'].create({
            'name': 'Packed', 'model_id': self.env.ref('sale.model_sale_order').id,
            'subject': 'Packed {{ object.name }}', 'partner_to': '{{ object.partner_id.id }}',
            'body_html': '<p>Your order is packed.</p>',
        })
        packed = self.env['online.order.stage'].create({
            'name': 'Packed', 'sequence': 15, 'mail_template_id': template.id,
        })
        order = self._tracked(self._create_order())
        self.assertEqual(order.online_next_stage_id, packed)
        order.action_online_next_stage()
        self._flush_tracking()
        self.assertEqual(order.stage_id, packed)
        self.assertTrue(self._messages_with_subject(order, 'Packed %s' % order.name))
        self.assertNotEqual(order.picking_ids.state, 'done', "the delivery leaves with Out for Delivery")
        self.assertEqual(order.online_next_stage_id, self.stage_out)

    def test_12_stage_activity(self):
        self.stage_out.write({'activity_user_id': self.manager_user.id, 'activity_summary': 'Call the driver'})
        order = self._create_order()
        order.stage_id = self.stage_out  # like a drag on the board
        self.assertEqual(order.activity_ids.summary, 'Call the driver')

    def test_30_delivery_day_badge(self):
        """Card badge: delivered today, or scheduled for a later day."""
        order = self._create_order()
        tz = order._online_timezone()
        now = datetime.now(tz)

        def promise(days):
            local = tz.localize(datetime.combine(now.date() + timedelta(days=days), time(18, 0)))
            order.delivery_promise_until = local.astimezone(pytz.utc).replace(tzinfo=None)

        promise(0)
        self.assertEqual((order.online_delivery_day, order.online_delivery_day_label), ('today', 'Today'))
        self.assertEqual(order.online_delivery_day_color, 5, "purple stripe")
        promise(1)
        self.assertEqual(order.online_delivery_day, 'scheduled')
        self.assertTrue(order.online_delivery_day_label.startswith('Tomorrow, '), order.online_delivery_day_label)
        self.assertEqual(order.online_delivery_day_color, 8, "blue stripe")
        promise(3)
        self.assertEqual(order.online_delivery_day, 'scheduled')
        self.assertNotIn('Tomorrow', order.online_delivery_day_label)
        promise(-1)
        self.assertEqual(order.online_delivery_day, 'past', "earlier days: no badge (Late shows instead)")
        self.assertEqual(order.online_delivery_day_color, 0)

    def test_13_counters_and_late(self):
        order = self._create_order()
        order.delivery_promise_until = '2020-01-01 10:00:00'
        self.assertTrue(order.online_is_late)
        self.assertEqual(order.online_time_status, 'late')
        self.assertIn(order, self.env['sale.order'].search([('online_is_late', '=', True)]))
        counters = self.env['sale.order'].get_online_order_counters()
        self.assertGreaterEqual(counters['overdue'], 1)
        order.stage_id = self.stage_delivered
        self.assertFalse(order.online_is_late)
        self.assertGreaterEqual(self.env['sale.order'].get_online_order_counters()['delivered_today'], 1)

    def test_14_quality_measures(self):
        order = self._create_order()
        order.write({'date_order': '2026-10-21 10:00:00', 'delivery_promise_until': '2026-10-21 13:00:00'})
        order.stage_id = self.stage_out
        order.write({'online_delivered_date': '2026-10-21 13:30:00'})
        self.assertEqual(order.online_delivery_minutes, 210)
        self.assertEqual(order.online_delay_minutes, 30)
        self.assertEqual(order.online_on_time_rate, 0)
        order.write({'online_delivered_date': '2026-10-21 12:00:00'})
        self.assertEqual(order.online_delay_minutes, 0)
        self.assertEqual(order.online_on_time_rate, 100)
        self.assertEqual(order.online_order_hour, 14, "10:00 UTC is 14:00 in Abu Dhabi")

    def test_15_existing_orders_on_install(self):
        delivered, waiting = self._create_order(), self._create_order()
        delivered._online_validate_delivery()
        self.assertEqual(delivered.picking_ids.state, 'done')
        cancelled = self._create_order()
        cancelled.action_cancel()
        orders = delivered | waiting | cancelled
        self.env.flush_all()
        self.env.cr.execute("UPDATE sale_order SET stage_id = NULL WHERE id IN %s", [tuple(orders.ids)])
        orders.invalidate_recordset(['stage_id'])
        self.env['sale.order']._online_orders_init_existing_orders()
        self.assertEqual(delivered.stage_id, self.stage_completed)
        self.assertEqual(waiting.stage_id, self.stage_new)
        self.assertEqual(cancelled.stage_id, self.stage_cancelled)

    def test_16_dispatch_values(self):
        order = self._create_order()
        self.assertEqual(order.online_coordinates, '25.0719120, 55.1527595', "Careem format")
        self.assertEqual(order.online_receiver_name, 'Receiver')
        self.assertEqual(order.online_receiver_phone, '+971500000002')
        self.assertEqual(order.online_driver_notes, 'Gate 2, next to the pharmacy')
        self.assertEqual(order.online_customer_email, order.partner_id.email)
        self.assertTrue(order.online_customer_email)
        self.assertEqual(order.online_cash_to_collect, order.amount_total, "nothing paid online")
        self.assertEqual(order.online_cash_to_collect_text, '%.2f' % order.amount_total)


@tagged('post_install', '-at_install')
class TestOnlineOrdersAddresses(OnlineOrdersCommon):

    def test_parse_coordinates(self):
        expected = (25.071912, 55.1527595)
        for text in [
            '25.0719120, 55.1527595',
            '25.0719120 55.1527595',
            'https://www.google.com/maps/place/Dubai/@25.0719120,55.1527595,17z/data=!3m1',
            'https://www.google.com/maps/place/X/@25.1,55.2,17z/data=!3d25.0719120!4d55.1527595',
            'https://maps.google.com/?q=25.0719120,55.1527595',
            'https://www.google.com/maps/search/?api=1&query=25.0719120%2C55.1527595',
        ]:
            lat, lng = parse_coordinates(text)
            self.assertAlmostEqual(lat, expected[0], places=6, msg=text)
            self.assertAlmostEqual(lng, expected[1], places=6, msg=text)
        for text in ['https://maps.app.goo.gl/abc123', 'Abu Dhabi', '200, 300']:
            with self.assertRaises(UserError, msg=text):
                parse_coordinates(text)

    def test_paste_coordinates_on_address(self):
        self.address.with_user(self.sales_user).coordinates_input = 'https://maps.google.com/?q=24.4539,54.3773'
        self.assertAlmostEqual(self.address.partner_latitude, 24.4539)
        self.assertEqual(self.address.partner_coordinates, '24.4539000, 54.3773000')

    def test_staff_adds_address(self):
        address = self._tracked(self.env['res.partner']).with_user(self.sales_user).create({
            'name': 'Office', 'parent_id': self.customer.id, 'type': 'delivery',
            'street': 'Office Tower', 'street2': 'Floor 5', 'city': 'Abu Dhabi',
            'partner_latitude': 24.45, 'partner_longitude': 54.37,
        })
        self.assertTrue(address.added_by_staff)
        self.assertFalse(self.address.added_by_staff, "added by the customer on the website")
        log = self.customer.message_ids.filtered(lambda m: 'Delivery address added by Sales Person' in str(m.body))
        self.assertTrue(log, "logged on the customer card")
        mail = self.env['mail.mail'].search([('subject', '=', 'Your delivery address was updated')])
        self.assertIn(self.customer, mail.recipient_ids, "the customer receives the email")

    def test_staff_edits_address(self):
        self.address.with_user(self.sales_user).street2 = 'Apt 1505'
        log = self.customer.message_ids.filtered(lambda m: 'Delivery address updated by Sales Person' in str(m.body))
        self.assertIn('Apt 1203 → Apt 1505', str(log.body))

    def test_customer_change_is_not_logged(self):
        count = len(self.customer.message_ids)
        self.address.sudo().street2 = 'Apt 1'  # website (sudo)
        self.assertEqual(len(self.customer.message_ids), count)

    def test_sales_cannot_delete_addresses(self):
        with self.assertRaises(UserError):
            self.address.with_user(self.sales_user).unlink()
        with self.assertRaises(UserError):
            self.address.with_user(self.sales_user).action_archive()
        self.address.with_user(self.manager_user).action_archive()
        self.assertFalse(self.address.active)

    def test_contacts_hide_delivery_addresses(self):
        domain = ['|', ('parent_id', '=', False), ('type', '!=', 'delivery')]
        found = self.env['res.partner'].search(domain + [('id', 'in', (self.customer | self.address).ids)])
        self.assertEqual(found, self.customer)
        action = self.env.ref('contacts.action_contacts')
        self.assertIn('search_default_hide_delivery_addresses', action.context)


@tagged('post_install', '-at_install')
class TestOnlineOrdersAccess(OnlineOrdersCommon):

    def test_sales_cannot_read_cost(self):
        with self.assertRaises(AccessError):
            self.meat.with_user(self.sales_user).read(['standard_price'])
        with self.assertRaises(AccessError):
            self.meat.product_tmpl_id.with_user(self.sales_user).read(['standard_price'])

    def test_other_apps_still_read_cost(self):
        for groups in ('stock.group_stock_user', 'sales_team.group_sale_salesman', 'account.group_account_invoice'):
            user = self.env['res.users'].create({
                'name': groups, 'login': groups, 'group_ids': [(6, 0, [self.env.ref(groups).id])],
            })
            self.assertEqual(self.meat.with_user(user).standard_price, 60.0, groups)

    def test_sales_user_runs_the_board(self):
        order = self._create_order()
        board_order = order.with_user(self.sales_user)
        board_order.action_online_next_stage()
        board_order.stage_id = self.stage_delivered  # drag
        self.assertEqual(order.stage_id, self.stage_delivered)
        self.assertEqual(order.picking_ids.state, 'done')
        self.assertEqual(board_order.online_coordinates, '25.0719120, 55.1527595')

    def test_sales_user_sees_website_orders_only(self):
        backend_order = self.env['sale.order'].create({'partner_id': self.customer.id})
        website_order = self._create_order()
        found = self.env['sale.order'].with_user(self.sales_user).search(
            [('id', 'in', (backend_order | website_order).ids)])
        self.assertEqual(found, website_order)

    def test_menus_per_role(self):
        Menu = self.env['ir.ui.menu']
        board = self.env.ref('online_orders.menu_online_orders_board')
        quality = self.env.ref('online_orders.menu_online_orders_quality')
        stages = self.env.ref('online_orders.menu_online_orders_stages')
        templates = self.env.ref('online_orders.menu_online_orders_templates')

        def visible(user):
            return Menu.with_user(user)._visible_menu_ids()

        self.assertIn(board.id, visible(self.sales_user))
        self.assertNotIn(quality.id, visible(self.sales_user), "Sales never see the quality report")
        self.assertIn(quality.id, visible(self.marketing_user))
        self.assertIn(templates.id, visible(self.marketing_user))
        self.assertNotIn(stages.id, visible(self.marketing_user))
        self.assertIn(quality.id, visible(self.manager_user))
        self.assertIn(stages.id, visible(self.manager_user))
        self.assertNotIn(templates.id, visible(self.manager_user), "templates are Marketing's")

        # By access rights, not only on screen: the report data can't be read by Sales
        order = self._create_order()
        measures = ['online_on_time_rate', 'online_delivery_minutes', 'online_delay_minutes']
        with self.assertRaises(AccessError):
            order.with_user(self.sales_user).read(measures)
        for user in (self.marketing_user, self.manager_user):
            self.assertTrue(order.with_user(user).read(measures))

    @mute_logger('odoo.addons.base.models.ir_rule')
    def test_sales_user_cannot_edit_stages(self):
        with self.assertRaises(AccessError):
            self.stage_new.with_user(self.sales_user).name = 'Renamed'


@tagged('post_install', '-at_install')
class TestOnlineOrdersDeliveredBy(OnlineOrdersCommon):
    """With stock_barcode_register: the delivery order needs "Delivered by"."""

    def setUp(self):
        super().setUp()
        if not self._has_delivered_by_rule():
            self.skipTest("stock_barcode_register is not installed")

    def test_dispatcher_is_delivered_by(self):
        order = self._create_order()
        order.with_user(self.sales_user).action_online_next_stage()
        self.assertEqual(order.stage_id, self.stage_out)
        self.assertEqual(order.picking_ids.employee_id.user_id, self.sales_user)
        self.assertEqual(order.picking_ids.state, 'done')

    def test_unauthorized_user_cannot_dispatch(self):
        user = new_test_user(self.env, login='not_authorized', groups='online_orders.group_online_orders_sales')
        order = self._create_order()
        with self.assertRaisesRegex(UserError, 'Delivered by'):
            order.with_user(user).action_online_next_stage()
        self.assertEqual(order.stage_id, self.stage_new)

    def test_warehouse_choice_is_kept(self):
        driver = self.env['hr.employee'].create({'name': 'Driver', 'stock_operation_authorized': True})
        order = self._create_order()
        order.picking_ids.employee_id = driver
        order.with_user(self.sales_user).action_online_next_stage()
        self.assertEqual(order.picking_ids.employee_id, driver)
