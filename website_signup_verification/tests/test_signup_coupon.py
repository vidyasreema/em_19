from odoo.exceptions import ValidationError
from odoo.tests import new_test_user, tagged

from .test_signup import SignupCommon


@tagged('post_install', '-at_install')
class TestSignupCoupon(SignupCommon):
    """Annex 3A task 5: the sign-up coupon (fixed code SIGNUP10)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env.ref('website_signup_verification.loyalty_program_signup_coupon')

    def _member(self, login, phone='+971 50 111 2233', issued=True):
        user = new_test_user(self.env, login=login, email=login, groups='base.group_portal')
        user.partner_id.write({'phone': phone, 'street': 'Tower A', 'city': 'Abu Dhabi',
                               'country_id': self.env.ref('base.ae').id,
                               'partner_latitude': 24.4539, 'partner_longitude': 54.3773})
        user.signup_coupon_issued = issued
        return user

    def _try(self, partner, amount=420):
        order = self._order(amount, self.island, partner)
        status = order._try_apply_code('SIGNUP10')
        if 'error' in status:
            return order, status['error']
        coupon, rewards = next(iter(status.items()))
        result = order._apply_program_reward(rewards, coupon)
        return order, result.get('error', '')

    def test_guest_and_old_accounts_are_refused(self):
        """5.2: typed by hand by a visitor who is not signed in (a guest order) is refused."""
        _order, error = self._try(self._address(24.4539, 54.3773, email='walk.in@example.com'))
        self.assertIn('for new accounts', error)
        old = self._member('old.member@example.com', issued=False)
        _order, error = self._try(old.partner_id)
        self.assertIn('created after confirming the email', error)

    def test_once_per_customer(self):
        member = self._member('first.time@example.com')
        order, error = self._try(member.partner_id)
        self.assertFalse(error)
        self.assertTrue(order.order_line.filtered(lambda l: l.reward_id.program_id == self.program))
        order.action_confirm()
        _order, error = self._try(member.partner_id)
        self.assertIn('once per customer and mobile number', error)

    def test_once_per_mobile(self):
        """5.3: a second account with a mobile that already used it gets nothing."""
        first = self._member('phone.one@example.com', phone='+971 50 777 1234')
        self._try(first.partner_id)[0].action_confirm()
        second = self._member('phone.two@example.com', phone='050 777 1234')
        _order, error = self._try(second.partner_id)
        self.assertIn('once per customer and mobile number', error)
        third = self._member('phone.three@example.com', phone='050 777 9999')
        _order, error = self._try(third.partner_id)
        self.assertFalse(error, "another mobile")

    def test_mobile_known_only_at_payment(self):
        """The mobile may come with the address: checked again before paying."""
        first = self._member('pay.one@example.com', phone='+971 50 555 0000')
        self._try(first.partner_id)[0].action_confirm()
        second = self._member('pay.two@example.com', phone='')
        order, error = self._try(second.partner_id)
        self.assertFalse(error)
        second.partner_id.phone = '0505550000'
        with self.assertRaises(ValidationError):
            order._check_cart_is_ready_to_be_paid()
        order._update_programs_and_rewards()
        self.assertFalse(order.order_line.filtered(lambda l: l.reward_id.program_id == self.program),
                         "removed when the cart is updated")

    def test_rate_and_minimum_from_the_programme(self):
        """5.4: the texts and the amount follow the programme."""
        order = self._order(380, self.island, self._address(24.4539, 54.3773))
        self.assertEqual(order._journey_signup_saving(self.website), 38.0)
        self.assertEqual(self.website._signup_coupon_title(), 'New here? Sign up and get 10% off')
        self.program.reward_ids.discount = 15
        self.assertEqual(order._journey_signup_saving(self.website), 57.0)
        self.assertEqual(self.website._signup_coupon_title(), 'New here? Sign up and get 15% off')
        self.program.rule_ids.minimum_amount = 500
        self.assertEqual(order._journey_signup_saving(self.website), 0.0, "below the minimum")
        self.website.signup_coupon_program_id = False
        self.assertEqual(self.website._signup_coupon_title(), '')

    def test_no_rules_without_the_programme(self):
        self.website.signup_coupon_program_id = False
        _order, error = self._try(self._address(24.4539, 54.3773, email='any@example.com'))
        self.assertFalse(error, "a normal promo code again")
