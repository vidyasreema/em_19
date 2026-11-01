import re

from markupsafe import Markup

from odoo import _, models
from odoo.exceptions import ValidationError


def phone_key(phone):
    """Last 9 digits of a mobile: +971 50 111 2233 and 050 111 2233 are the same."""
    digits = re.sub(r'\D', '', phone or '')
    return digits[-9:] if len(digits) >= 7 else ''


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ──────────────────────────────────────────────────────────────────────────
    # Sign-up coupon rules (Annex 3A task 5)
    # ──────────────────────────────────────────────────────────────────────────

    def _program_check_compute_points(self, programs):
        """The sign-up coupon is refused (typed by hand too) when the rules of
        task 5 fail; an applied one is removed when the cart is updated."""
        result = super()._program_check_compute_points(programs)
        for program in programs:
            if 'error' not in result.get(program, {}):
                error = self._signup_coupon_error(program)
                if error:
                    result[program] = {'error': error}
        return result

    def _signup_coupon_error(self, program):
        """:return: why this order may not use the sign-up coupon ('' when it may)"""
        self.ensure_one()
        website = self.website_id
        if not website or program != website._signup_coupon_program():
            return ''
        user = self.partner_id.with_context(active_test=False).user_ids.filtered('active')[:1]
        if not user:
            return _("The sign-up offer is for new accounts. Sign up or sign in to use it.")
        if not user.sudo().signup_coupon_issued:
            return _("The sign-up offer is only for accounts created after confirming the email.")
        if self._signup_coupon_used(program):
            return _("The sign-up offer can only be used once per customer and mobile number.")
        return ''

    def _signup_phone_key(self):
        """Mobile of the customer (the receiver's when the customer has none)."""
        self.ensure_one()
        return phone_key(self.partner_id.phone) or phone_key(self.partner_shipping_id.phone)

    def _signup_coupon_used(self, program):
        """Whether this customer, or another account with the same mobile,
        already used the sign-up coupon on a confirmed order."""
        self.ensure_one()
        used_orders = self.env['sale.order.line'].sudo().search([
            ('reward_id.program_id', '=', program.id),
            ('order_id', '!=', self._origin.id),
            ('order_id.state', '=', 'sale'),
        ]).order_id
        if not used_orders:
            return False
        commercial = self.partner_id.commercial_partner_id
        phone = self._signup_phone_key()
        return any(
            order.partner_id.commercial_partner_id == commercial or (phone and order._signup_phone_key() == phone)
            for order in used_orders
        )

    def _check_cart_is_ready_to_be_paid(self):
        """Last check before the payment: the mobile may be known only now."""
        for order in self:
            for program in order.order_line.reward_id.program_id:
                error = order._signup_coupon_error(program)
                if error:
                    raise ValidationError(error)
        return super()._check_cart_is_ready_to_be_paid()

    # ──────────────────────────────────────────────────────────────────────────
    # Guest order with the email of an account
    # ──────────────────────────────────────────────────────────────────────────

    def _action_confirm(self):
        result = super()._action_confirm()
        for order in self:
            order._signup_link_guest_order()
        return result

    def _signup_link_guest_order(self):
        """A guest order placed with the email of an account joins that account
        (My orders): its customer becomes a delivery address of the account.
        Only for accounts that proved the email (code, Google / Facebook); for
        the others it is tagged for the daily check."""
        self.ensure_one()
        website = self.website_id
        guest = self.partner_id.sudo()
        if (
            not (website.signup_verification and guest.email_normalized)
            or guest.parent_id
            or guest.with_context(active_test=False).user_ids
            or guest == website.user_id.partner_id
        ):
            return
        account = self.env['res.users']._signup_find_account(guest.email_normalized)
        if not account.active:
            return
        if not account._signup_email_proven():
            guest._signup_flag_duplicates(account.partner_id, order=self)
            return
        # A delivery address keeps its own address (a contact would take the account's)
        guest.write({'parent_id': account.partner_id.id, 'type': 'delivery'})
        self.sudo().message_post(
            body=Markup(_("Guest order with the email of %(account)s: added to that account "
                          "(My orders), with its address as a delivery address.")) % {
                'account': account.partner_id._get_html_link()},
            subtype_xmlid='mail.mt_note',
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Order page: what the guest loses, at the rate of the programme (5.4)
    # ──────────────────────────────────────────────────────────────────────────

    def _journey_signup_saving(self, website):
        program = website._signup_coupon_program()
        if not program:
            return super()._journey_signup_saving(website)
        reward = website._signup_coupon_reward()
        if not reward:
            return 0.0
        minimum = min(program.rule_ids.mapped('minimum_amount') or [0.0])
        if self.currency_id.compare_amounts(self._journey_items_amount(), minimum) < 0:
            return 0.0
        base, _above = self._journey_discount_base()
        return self.currency_id.round(base * reward.discount / 100.0)
