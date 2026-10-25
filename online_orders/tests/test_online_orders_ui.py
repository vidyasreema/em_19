from odoo import Command
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestOnlineOrdersUi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].get_current_website()
        cls.env['store.settings'].get_store_settings(cls.website.id)
        cls.product = cls.env['product.product'].create({
            'name': 'Tour Ribeye', 'type': 'consu', 'is_storable': True,
            'list_price': 100.0, 'sale_ok': True, 'website_published': True,
        })
        cls.portal_user = new_test_user(
            cls.env, login='online_portal', name='Portal Customer', groups='base.group_portal',
            email='portal.customer@example.com')
        cls.customer = cls.portal_user.partner_id
        # stock_barcode_register (if installed): the dispatchers are authorized employees
        if 'hr.employee' in cls.env and 'stock_operation_authorized' in cls.env['hr.employee']._fields:
            for user in (cls.env.user, cls.env.ref('base.user_admin')):
                if user.employee_ids:
                    user.employee_ids[:1].stock_operation_authorized = True
                else:
                    cls.env['hr.employee'].create({'name': user.name, 'user_id': user.id, 'stock_operation_authorized': True})

    def _order(self, name):
        order = self.env['sale.order'].create({
            'name': name,
            'partner_id': self.customer.id,
            'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 1})],
        })
        order.action_confirm()
        return order

    def test_board(self):
        order_a, order_b = self._order('TOUR-A'), self._order('TOUR-B')
        self.start_tour('/odoo/action-online_orders.action_online_orders_board', 'online_orders_board', login='admin')
        self.assertEqual(order_a.stage_id, self.env.ref('online_orders.stage_delivered'))
        self.assertEqual(order_a.picking_ids.state, 'done')
        self.assertEqual(order_b.stage_id, self.env.ref('online_orders.stage_cancelled'))
        self.assertEqual(order_b.state, 'cancel')
        self.assertEqual(order_b.online_cancel_reason, 'customer')

    def test_portal_shows_on_the_way(self):
        """Annex 4, check 4: "On the way", not "Delivered", after departure."""
        order = self._order('PORTAL-1')
        order.action_online_next_stage()
        self.assertEqual(order.delivery_status, 'full', "Odoo itself would say delivered")
        self.authenticate('online_portal', 'online_portal')
        orders_page = self.url_open('/my/orders').text
        self.assertIn('On the way', orders_page)
        order_page = self.url_open(order.get_portal_url()).text
        self.assertIn('On the way', order_page)
        self.assertNotIn('Last Delivery Orders', order_page)
