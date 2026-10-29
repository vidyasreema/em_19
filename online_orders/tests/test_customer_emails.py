from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.mail.tests.common import MockEmail
from odoo.addons.payment.tests.common import PaymentCommon
from odoo.addons.sale.models.payment_transaction import PaymentTransaction as SalePaymentTransaction

from .common import OnlineOrdersCommon


@tagged('post_install', '-at_install')
class TestNextOrderCoupon(OnlineOrdersCommon, MockEmail):
    """The next-order coupon is given when the order is delivered, in the Delivered email."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env['loyalty.program'].create({
            'name': 'Next order 10%',
            'program_type': 'next_order_coupons',
            'trigger': 'auto',
            'applies_on': 'future',
            'rule_ids': [Command.create({'minimum_qty': 1, 'reward_point_amount': 1, 'reward_point_mode': 'order'})],
            'reward_ids': [Command.create({'reward_type': 'discount', 'discount': 10, 'required_points': 1})],
            'communication_plan_ids': [Command.create({
                'trigger': 'create', 'mail_template_id': cls.env.ref('loyalty.mail_template_loyalty_card').id})],
        })

    def _coupon_emails(self):
        return [m for m in self._mails if 'coupon' in m['subject'].lower()] \
            + list(self._new_mails.filtered(lambda m: m.model == 'loyalty.card'))

    def test_coupon_on_hold_until_delivered(self):
        with self.mock_mail_gateway():
            order = self._tracked(self._create_order())
        coupon = order.coupon_point_ids.coupon_id
        self.assertEqual(len(coupon), 1)
        self.assertTrue(order.online_coupon_held)
        self.assertEqual(coupon.points, 0, "no coupon before the delivery")
        self.assertFalse(order.online_next_order_coupons)
        self.assertFalse(self._coupon_emails(), "no coupon email at the confirmation")

        with self.mock_mail_gateway():
            order.action_online_next_stage()
            order.action_online_next_stage()
            self._flush_tracking()
        self.assertEqual(order.stage_id, self.stage_delivered)
        self.assertFalse(order.online_coupon_held)
        self.assertEqual(coupon.points, 1, "the coupon can be used now")
        delivered = self._messages_with_subject(order, 'Thank you for your order')
        self.assertIn(coupon.code, delivered.body, "the code is in the Delivered email")
        self.assertFalse(self._coupon_emails(), "no coupon email of its own")

    def test_coupon_used_after_delivery_only(self):
        order = self._create_order()
        coupon = order.coupon_point_ids.coupon_id
        cart = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.meat.id, 'product_uom_qty': 1})],
        })
        result = cart._try_apply_code(coupon.code)
        self.assertEqual(result.get('error'), "This coupon can be used once your order %s is delivered." % order.name)
        order.action_online_next_stage()
        order.action_online_next_stage()
        self.assertNotIn('error', cart._try_apply_code(coupon.code), "delivered: the coupon works")

    def test_cancelled_before_delivery_gives_no_coupon(self):
        order = self._create_order()
        coupon = order.coupon_point_ids.coupon_id
        order._action_cancel()
        self.assertFalse(coupon.exists() and coupon.points, "no coupon and no negative points")

    def test_cancelled_after_delivery_takes_the_coupon_back(self):
        order = self._create_order()
        coupon = order.coupon_point_ids.coupon_id
        order.action_online_next_stage()
        order.action_online_next_stage()
        self.assertEqual(coupon.points, 1)
        order._action_cancel()
        self.assertFalse(coupon.exists() and coupon.points, "returned: the coupon is taken back")

    def test_order_from_the_backend_keeps_odoo_flow(self):
        with self.mock_mail_gateway():
            order = self._create_order(website_id=False)
        self.assertFalse(order.online_coupon_held)
        self.assertEqual(order.coupon_point_ids.coupon_id.points, 1)
        self.assertTrue(self._coupon_emails())


@tagged('post_install', '-at_install')
class TestOnlineOrderInvoice(PaymentCommon, OnlineOrdersCommon, MockEmail):
    """Automatic invoice of a paid website order: no invoice email, no "assigned" email."""

    def _pay(self, order):
        """Paid online with automatic invoice; returns the subjects of the emails."""
        self.env['ir.config_parameter'].sudo().set_param('sale.automatic_invoice', 'True')
        self.env['ir.config_parameter'].sudo().set_param('sale.async_emails', 'False')
        tx = self._create_transaction(
            flow='redirect', sale_order_ids=[order.id], state='done', amount=order.amount_total,
            currency_id=order.currency_id.id, partner_id=order.partner_id.id, reference=order.name)
        sent = self.env['payment.transaction']
        send_invoice = SalePaymentTransaction._send_invoice

        def _send_invoice(txs):
            nonlocal sent
            sent |= txs
            return send_invoice(txs)

        with mute_logger('odoo.addons.sale.models.payment_transaction'), self.mock_mail_gateway(), \
                patch.object(SalePaymentTransaction, '_send_invoice', _send_invoice):
            self._tracked(tx)._post_process()
        self.assertEqual(order.state, 'sale')
        self.assertTrue(tx.invoice_ids, "the invoice is still created")
        subjects = [m.subject or '' for m in self._new_mails] + [m['subject'] for m in self._mails]
        return sent, subjects

    def _draft_order(self, **values):
        salesperson = self.env['res.users'].create({
            'name': 'Website Salesperson', 'login': 'web_salesperson', 'email': 'web.sales@example.com',
            'group_ids': [Command.link(self.env.ref('sales_team.group_sale_salesman').id)],
            'notification_type': 'email',
        })
        return self._tracked(self.env['sale.order']).create({
            'partner_id': self.customer.id,
            'website_id': self.website.id,
            'user_id': salesperson.id,
            'order_line': [Command.create({'product_id': self.meat.id, 'product_uom_qty': 1})],
            **values,
        })

    def test_website_order_invoice_not_emailed(self):
        sent, subjects = self._pay(self._draft_order())
        self.assertFalse(sent, "the invoice is not emailed")
        self.assertFalse([s for s in subjects if 'Invoice' in s], subjects)

    def test_backend_order_keeps_odoo_flow(self):
        sent, subjects = self._pay(self._draft_order(website_id=False))
        self.assertTrue(sent, "the invoice is emailed")
        self.assertTrue([s for s in subjects if 'assigned to' in s and 'Invoice' in s], subjects)
