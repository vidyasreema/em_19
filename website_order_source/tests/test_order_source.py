from odoo import http
from odoo.http import root
from odoo.tests import new_test_user, tagged

from odoo.addons.website_purchase_journey.tests.test_order import OrderCommon


@tagged('post_install', '-at_install')
class TestOrderSource(OrderCommon):
    """"How did you hear about us?" on the confirmation page."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website.order_source_question = True
        cls.instagram = cls.env.ref('website_order_source.source_instagram')
        cls.friend = cls.env.ref('website_order_source.source_friend')

    def setUp(self):
        super().setUp()
        self.order = self._order(420, self.island, self._address(24.4539, 54.3773, name='Source Guest',
                                                                 email='source.guest@example.com'))
        self.order.action_confirm()
        session = self.authenticate(None, None)
        session['sale_last_order_id'] = self.order.id
        root.session_store.save(session)

    def _answer(self, source):
        return self.url_open('/shop/order/source', data={
            'source_id': source.id, 'csrf_token': http.Request.csrf_token(self)})

    def _notes(self):
        return self.order.message_ids.filtered(lambda m: 'How did you hear about us?' in (m.body or ''))

    def test_one_tap_answer(self):
        page = self.url_open('/shop/confirmation').text
        self.assertIn('How did you hear about us?', page)
        self.assertIn('One tap is enough.', page)
        for name in ('Instagram', 'Facebook', 'A friend'):
            self.assertIn(name, page)

        response = self._answer(self.instagram)
        self.assertEqual(self.order.order_source_id, self.instagram)
        self.assertIn('Thank you!', response.text)
        self.assertIn('o_order_source_answer', response.text, "only the answer is shown")
        self.assertNotIn('o_order_source_option', response.text, "no more buttons")
        note = self._notes()
        self.assertEqual(len(note), 1, "in the order history")
        self.assertIn('Instagram', note.body)
        self.assertEqual(note.author_id, self.order.partner_id, "written by the customer")

        self._answer(self.friend)
        self.assertEqual(self.order.order_source_id, self.instagram, "answered once")
        self.assertEqual(len(self._notes()), 1)

    def test_archived_answer_is_ignored(self):
        self.friend.active = False
        self.assertNotIn('A friend', self.url_open('/shop/confirmation').text)
        self._answer(self.friend)
        self.assertFalse(self.order.order_source_id)

    def test_switched_off(self):
        self.website.order_source_question = False
        self.assertNotIn('o_order_source', self.url_open('/shop/confirmation').text)
        self._answer(self.instagram)
        self.assertFalse(self.order.order_source_id)

    def test_no_order_in_the_session(self):
        self.authenticate(None, None)
        response = self._answer(self.instagram)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.order.order_source_id)

    def test_report_counts(self):
        self.order.sudo()._order_source_answer(self.instagram)
        self.assertEqual(self.instagram.order_count, 1)
        groups = self.env['sale.order']._read_group(
            [('website_id', '!=', False), ('state', '=', 'sale'), ('order_source_id', '!=', False)],
            ['order_source_id'], ['__count'])
        self.assertIn((self.instagram, 1), groups)


@tagged('post_install', '-at_install')
class TestOrderSourceOrderPage(OrderCommon):
    """The same question on the order page (My Orders)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website.order_source_question = True
        cls.facebook = cls.env.ref('website_order_source.source_facebook')
        cls.customer = new_test_user(cls.env, login='source.customer', groups='base.group_portal')

    def setUp(self):
        super().setUp()
        self.order = self._order(420, self.island, self.customer.partner_id)
        self.order.action_confirm()

    def _answer(self, source, **data):
        return self.url_open('/my/orders/%s/source' % self.order.id, data={
            'source_id': source.id, 'csrf_token': http.Request.csrf_token(self), **data})

    def test_customer_answers_on_the_order_page(self):
        self.authenticate('source.customer', 'source.customer')
        page = self.url_open('/my/orders/%s' % self.order.id).text
        self.assertIn('How did you hear about us?', page)
        self.assertIn('One tap is enough.', page)

        response = self._answer(self.facebook)
        self.assertEqual(self.order.order_source_id, self.facebook)
        self.assertIn('Thank you!', response.text, "back on the order page")
        self.assertIn('o_order_source_answer', response.text)
        self.assertNotIn('o_order_source_option', response.text)
        note = self.order.message_ids.filtered(lambda m: 'How did you hear about us?' in (m.body or ''))
        self.assertIn('Facebook', note.body, "in the order history")
        self.assertEqual(note.author_id, self.customer.partner_id)

    def test_answer_with_the_link_of_the_order(self):
        self.authenticate(None, None)
        token = self.order._portal_ensure_token()
        self.assertIn('o_order_source', self.url_open('/my/orders/%s?access_token=%s' % (self.order.id, token)).text)
        self._answer(self.facebook, access_token=token)
        self.assertEqual(self.order.order_source_id, self.facebook)

    def test_someone_else_cannot_answer(self):
        new_test_user(self.env, login='source.other', groups='base.group_portal')
        self.authenticate('source.other', 'source.other')
        self._answer(self.facebook)
        self.assertFalse(self.order.order_source_id)

    def test_switched_off(self):
        self.website.order_source_question = False
        self.authenticate('source.customer', 'source.customer')
        self.assertNotIn('o_order_source', self.url_open('/my/orders/%s' % self.order.id).text)

    def test_track_your_order(self):
        self.authenticate('source.customer', 'source.customer')
        page = self.url_open('/my/orders/%s/track' % self.order.id).text
        self.assertIn('How did you hear about us?', page)
        response = self._answer(self.facebook, back='track')
        self.assertEqual(self.order.order_source_id, self.facebook)
        self.assertIn('/track', response.url, "back on Track your order")
        self.assertIn('Thank you!', response.text)
