from odoo.tests import new_test_user, tagged

from .test_signup import SignupCommon


@tagged('post_install', '-at_install')
class TestGuestOrderOfAnAccount(SignupCommon):
    """A guest order placed with the email of an existing account."""

    def _member(self, login, issued=True, oauth_uid=False):
        user = new_test_user(self.env, login=login, email=login, groups='base.group_portal')
        user.partner_id.write({'street': 'Villa 1', 'city': 'Al Ain'})
        user.write({'signup_coupon_issued': issued, 'oauth_uid': oauth_uid})
        return user

    def _my_orders(self, user):
        return self.env['sale.order'].with_user(user).search([('state', '=', 'sale')])

    def test_proven_account_gets_the_order(self):
        member = self._member('proven@example.com')
        guest, order = self._guest('Proven@example.com', name='Guest Name')
        self.assertEqual(guest.parent_id, member.partner_id)
        self.assertEqual(guest.type, 'delivery')
        self.assertEqual(guest.street, 'Tower A', "the order keeps its delivery address")
        self.assertEqual(member.partner_id.street, 'Villa 1', "the account keeps its address")
        self.assertIn(order, self._my_orders(member))
        self.assertIn('added to that account', order.message_ids[0].body)

    def test_google_account_gets_the_order(self):
        member = self._member('google.member@example.com', issued=False, oauth_uid='g-9')
        guest, order = self._guest('google.member@example.com')
        self.assertEqual(guest.parent_id, member.partner_id)
        self.assertIn(order, self._my_orders(member))

    def test_old_account_is_flagged(self):
        member = self._member('old.account@example.com', issued=False)
        guest, order = self._guest('old.account@example.com')
        self.assertFalse(guest.parent_id)
        self.assertNotIn(order, self._my_orders(member))
        self.assertIn(self.env.ref('website_signup_verification.partner_tag_duplicate_email'), guest.category_id)
        self.assertIn(order.name, guest.message_ids[0].body)

    def test_no_account_or_switch_off(self):
        guest, _order = self._guest('nobody.here@example.com')
        self.assertFalse(guest.parent_id or guest.category_id)
        self.website.signup_verification = False
        self._member('switched.off@example.com')
        guest, _order = self._guest('switched.off@example.com')
        self.assertFalse(guest.parent_id)
