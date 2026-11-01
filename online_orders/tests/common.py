from odoo import Command
from odoo.tests import new_test_user

from odoo.addons.website_sale.tests.common import WebsiteSaleCommon


class OnlineOrdersCommon(WebsiteSaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['store.settings'].get_store_settings(cls.website.id)
        ref = cls.env.ref
        cls.stage_new = ref('online_orders.stage_new')
        cls.stage_out = ref('online_orders.stage_out_for_delivery')
        cls.stage_delivered = ref('online_orders.stage_delivered')
        cls.stage_completed = ref('online_orders.stage_completed')
        cls.stage_cancelled = ref('online_orders.stage_cancelled')

        cls.meat = cls.env['product.product'].create({
            'name': 'Ribeye', 'type': 'consu', 'is_storable': True,
            'list_price': 100.0, 'standard_price': 60.0,
            'sale_ok': True, 'website_published': True,
        })
        cls.customer = cls.env['res.partner'].create({
            'name': 'Online Customer', 'email': 'customer@example.com', 'phone': '+971500000001',
        })
        # Added by the customer on the website (sudo): not logged as a staff change
        cls.address = cls.env['res.partner'].sudo().create({
            'name': 'Receiver', 'parent_id': cls.customer.id, 'type': 'delivery',
            'street': 'Tower A', 'street2': 'Apt 1203', 'city': 'Abu Dhabi',
            'country_id': cls.env.ref('base.ae').id, 'phone': '+971500000002',
            'partner_latitude': 25.071912, 'partner_longitude': 55.1527595,
            'address_label': 'home', 'delivery_directions': 'Gate 2, next to the pharmacy',
        })

        cls.sales_user = new_test_user(
            cls.env, login='online_sales', name='Sales Person',
            groups='online_orders.group_online_orders_sales')
        cls.marketing_user = new_test_user(
            cls.env, login='online_marketing', name='Marketing Person',
            groups='online_orders.group_online_orders_marketing')
        cls.manager_user = new_test_user(
            cls.env, login='online_manager', name='Manager Person',
            groups='online_orders.group_online_orders_management')
        cls._authorize_for_deliveries(cls.env.user, cls.sales_user, cls.marketing_user, cls.manager_user)

    @classmethod
    def _has_delivered_by_rule(cls):
        """stock_barcode_register installed: deliveries need an authorized "Delivered by"."""
        return 'hr.employee' in cls.env and 'stock_operation_authorized' in cls.env['hr.employee']._fields

    @classmethod
    def _authorize_for_deliveries(cls, *users):
        """Like in real use: the people dispatching are authorized employees."""
        if not cls._has_delivered_by_rule():
            return {}
        employees = {}
        for user in users:
            employee = user.employee_ids[:1]
            if employee:
                employee.stock_operation_authorized = True
            else:
                employee = cls.env['hr.employee'].create({
                    'name': user.name, 'user_id': user.id, 'stock_operation_authorized': True})
            employees[user] = employee
        return employees

    def _create_order(self, partner=None, product=None, qty=2.0, **values):
        order = self.env['sale.order'].create({
            'partner_id': (partner or self.customer).id,
            'partner_shipping_id': (self.address if not partner else partner).id,
            'website_id': self.website.id,
            'order_line': [Command.create({'product_id': (product or self.meat).id, 'product_uom_qty': qty})],
            **values,
        })
        order.action_confirm()
        # Like a real order (the cart exists before it is confirmed): later changes
        # are tracked. Odoo does not track a record in its creation transaction.
        self._flush_tracking()
        return order

    @staticmethod
    def _tracked(record):
        """The test base disables tracking (and so the stage emails): enable it."""
        return record.with_context(tracking_disable=False, mail_notrack=False)

    def _flush_tracking(self):
        """Tracking (and the stage emails) run at the end of the transaction."""
        self.env.flush_all()
        self.env.cr.precommit.run()

    def _messages_with_subject(self, record, text):
        return record.message_ids.filtered(lambda m: text in (m.subject or ''))
