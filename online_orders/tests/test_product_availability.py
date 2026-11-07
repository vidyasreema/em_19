from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.website_sale.tests.common import MockRequest

from .common import OnlineOrdersCommon


@tagged('post_install', '-at_install')
class TestProductAvailability(OnlineOrdersCommon):
    """Annex 4A: Product Availability switch."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.out_ribbon = cls.website._online_out_of_stock_ribbon()
        cls.sale_ribbon = cls.env.ref('website_sale.sale_ribbon')
        cls.sold_out_ribbon = cls.env.ref('website_sale.sold_out_ribbon')
        cls.weight = cls.env['product.attribute'].create({
            'name': 'Weight',
            'value_ids': [Command.create({'name': '250g'}), Command.create({'name': '500g'})],
        })
        cls.rump = cls.env['product.template'].create({
            'name': 'Black Onyx Rump', 'type': 'consu', 'list_price': 89.0,
            'sale_ok': True, 'is_published': True,
            'attribute_line_ids': [Command.create({
                'attribute_id': cls.weight.id,
                'value_ids': [Command.set(cls.weight.value_ids.ids)],
            })],
        })
        cls.rump_250, cls.rump_500 = cls.rump.product_variant_ids
        cls.unpublished = cls.env['product.template'].create({
            'name': 'Hidden Brisket', 'type': 'consu', 'sale_ok': True, 'is_published': False,
        })
        cls.plain_user = new_test_user(cls.env, login='plain_internal', name='Plain User',
                                       groups='base.group_user')

    def _switch(self, template, available, user=None):
        return self.env['product.template'].with_user(user or self.sales_user).online_set_availability(
            template.id, available)

    def _row(self, template, user=None):
        rows = self.env['product.template'].with_user(user or self.sales_user).online_availability_list()
        return next((row for row in rows if row['id'] == template.id), None)

    def _cart(self, *products):
        return self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'website_id': self.website.id,
            'order_line': [Command.create({'product_id': p.id, 'product_uom_qty': 1}) for p in products],
        })

    # ── 1. Availability screen ──────────────────────────────────────────

    def test_list_shows_published_products_name_and_state(self):
        row = self._row(self.rump)
        self.assertEqual({'id': self.rump.id, 'name': 'Black Onyx Rump', 'out_of_stock': False}, row)
        self.assertIsNone(self._row(self.unpublished), "only published website products are listed")

    def test_switch_out_of_stock_and_back(self):
        result = self._switch(self.rump, available=False)
        self.assertTrue(result['out_of_stock'])
        self.assertEqual("Saved: Black Onyx Rump is out of stock", result['message'])
        self.assertEqual(self.out_ribbon, self.rump.website_ribbon_id)
        self.assertTrue(self._row(self.rump)['out_of_stock'])

        result = self._switch(self.rump, available=True)
        self.assertFalse(result['out_of_stock'])
        self.assertEqual("Saved: Black Onyx Rump is available", result['message'])
        self.assertFalse(self.rump.website_ribbon_id)
        self.assertIn('Product Availability: set to Available.', self.rump.message_ids[0].body)
        self.assertEqual(self.sales_user.partner_id, self.rump.message_ids[0].author_id)

    def test_available_removes_any_ribbon(self):
        """2.2: a product with the Sale ribbon (also on a variant) shows no ribbon."""
        self.rump.website_ribbon_id = self.sale_ribbon
        self.rump_500.variant_ribbon_id = self.sale_ribbon
        self._switch(self.rump, available=True)
        self.assertFalse(self.rump.website_ribbon_id)
        self.assertFalse(self.rump_500.variant_ribbon_id)

    def test_out_of_stock_clears_variant_ribbons(self):
        """The variant ribbon wins on the website and in the feed: it is cleared."""
        self.rump_250.variant_ribbon_id = self.sale_ribbon
        self._switch(self.rump, available=False)
        self.assertFalse(self.rump_250.variant_ribbon_id)
        self.assertTrue(self.rump._online_is_out_of_stock(self.website, self.rump_250))

    def test_sold_out_ribbon_shows_out_of_stock(self):
        """Same rule as the website and the Meta feed."""
        self.rump.website_ribbon_id = self.sold_out_ribbon
        self.assertTrue(self._row(self.rump)['out_of_stock'])

    def test_access(self):
        """1.5: Online Orders users can use the screen, other users cannot."""
        self._switch(self.rump, available=False, user=self.sales_user)
        with self.assertRaises(AccessError):
            self._row(self.rump, user=self.plain_user)
        with self.assertRaises(AccessError):
            self._switch(self.rump, available=True, user=self.plain_user)

    # ── 2. Website: an out-of-stock product cannot be sold ──────────────

    def test_cannot_add_to_cart(self):
        self._switch(self.rump, available=False)
        self.assertFalse(self.rump._is_add_to_cart_possible())
        cart = self._cart(self.meat)
        with MockRequest(self.env, website=self.website, sale_order_id=cart.id):
            result = cart._cart_add(self.rump_250.id, 1)
        self.assertEqual(0, result['quantity'])
        self.assertIn('is out of stock and cannot be added', result['warning'])
        self.assertNotIn(self.rump_250, cart.order_line.product_id)

        self._switch(self.rump, available=True)
        self.assertTrue(self.rump._is_add_to_cart_possible())
        with MockRequest(self.env, website=self.website, sale_order_id=cart.id):
            cart._cart_add(self.rump_250.id, 1)
        self.assertIn(self.rump_250, cart.order_line.product_id)

    def test_switch_removes_product_from_open_carts_only(self):
        cart = self._cart(self.rump_250, self.meat)
        confirmed = self._create_order(product=self.rump_250)
        backend_quote = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({'product_id': self.rump_250.id})],
        })

        self._switch(self.rump, available=False)

        self.assertEqual(self.meat, cart.order_line.product_id, "the cart keeps the other products")
        self.assertIn('Black Onyx Rump', cart.shop_warning)
        self.assertIn(self.rump_250, confirmed.order_line.product_id, "confirmed orders are not changed")
        self.assertIn(self.rump_250, backend_quote.order_line.product_id, "backend quotations are not changed")

    def test_payment_refused_for_out_of_stock_product(self):
        """Safety net: never charge an out-of-stock product."""
        self._switch(self.rump, available=False)
        cart = self._cart(self.rump_250)  # created directly, without the website checks
        with self.assertRaisesRegex(ValidationError, 'Black Onyx Rump is out of stock'):
            cart._check_cart_is_ready_to_be_paid()

    def test_backend_and_pos_can_still_sell(self):
        """The block is for the website only."""
        self._switch(self.rump, available=False)
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({'product_id': self.rump_250.id})],
        })
        order.action_confirm()
        self.assertEqual('sale', order.state)

    def test_meta_feed_follows_the_switch(self):
        """2.4: the feed reads the same ribbons."""
        feed_ribbons = self.website._online_out_of_stock_ribbons()
        self.assertIn(self.out_ribbon, feed_ribbons)
        self.assertIn(self.sold_out_ribbon, feed_ribbons)
        self.assertNotIn(self.sale_ribbon, feed_ribbons)
