import logging

from odoo import _, models
from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.tools import format_amount

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ──────────────────────────────────────────────────────────────────────────
    # Coupon base (Annex 3 §9): below the free-delivery threshold a coupon
    # applies to the full amount; once delivery is free, only to the amount
    # above the threshold. Example (threshold 400): 399 -> on 399, 405 -> on 5.
    # ──────────────────────────────────────────────────────────────────────────

    def _journey_rule_applies(self):
        self.ensure_one()
        return bool(self.website_id.journey_enabled)

    def _journey_free_threshold(self):
        """Free-delivery threshold of the delivery method (order currency), or None."""
        self.ensure_one()
        carrier = self.carrier_id
        if not (carrier and carrier.free_over):
            return None
        return carrier._compute_currency(self, carrier.amount, 'company_to_pricelist')

    def _journey_product_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: line.product_id and not line.display_type
            and not line.is_delivery and not line.is_reward_line)

    def _journey_items_amount(self):
        """Products total, tax included (what the free-delivery threshold is compared with)."""
        return sum(self._journey_product_lines().mapped('price_total'))

    def _journey_discount_base(self):
        """(amount a percentage coupon applies to, True if only the amount above the threshold)."""
        self.ensure_one()
        amount = self._journey_items_amount()
        threshold = self._journey_free_threshold()
        if threshold is not None and self.currency_id.compare_amounts(amount, threshold) >= 0:
            return amount - threshold, True
        return amount, False

    def _discountable_order(self, reward):
        discountable, discountable_per_tax = super()._discountable_order(reward)
        if (
            not self._journey_rule_applies()
            or reward.program_id.is_payment_program
            or reward.discount_mode != 'percent'
            or not discountable
        ):
            return discountable, discountable_per_tax
        threshold = self._journey_free_threshold()
        if threshold is None or self.currency_id.compare_amounts(discountable, threshold) < 0:
            return discountable, discountable_per_tax
        # Delivery is free: keep only the share of each tax group above the threshold
        ratio = max(discountable - threshold, 0.0) / discountable
        return discountable * ratio, {taxes: amount * ratio for taxes, amount in discountable_per_tax.items()}

    # ──────────────────────────────────────────────────────────────────────────
    # Order page
    # ──────────────────────────────────────────────────────────────────────────

    def _journey_money(self, amount):
        return format_amount(self.env, amount, self.currency_id)

    def _journey_coupon_message(self, reward):
        """'10% off applied on AED 5.00, the amount above AED 400.00, because delivery is now free.'"""
        self.ensure_one()
        title = reward.description or reward.program_id.name
        base, above = self._journey_discount_base()
        if reward.discount_mode != 'percent':
            return _("%s applied.", title)
        if above:
            return _("%(coupon)s applied on %(base)s, the amount above %(threshold)s, because delivery is now free.",
                     coupon=title, base=self._journey_money(base),
                     threshold=self._journey_money(self._journey_free_threshold()))
        return _("%(coupon)s applied on the full amount, %(base)s.", coupon=title, base=self._journey_money(base))

    def _journey_delivery_base_fee(self):
        """Delivery fee before "free above", tax included (shown crossed out when free)."""
        self.ensure_one()
        carrier = self.carrier_id
        if not carrier or carrier.delivery_type != 'fixed':
            return 0.0
        taxes = self.fiscal_position_id.map_tax(carrier.product_id.taxes_id._filter_taxes_by_company(self.company_id))
        return taxes.compute_all(carrier.fixed_price, currency=self.currency_id,
                                 product=carrier.product_id)['total_included']

    def _journey_signup_saving(self, website):
        """What a guest saves by signing up: the welcome coupon on this order."""
        self.ensure_one()
        # sudo: website visitors cannot read the loyalty programs
        # An archived program means no welcome coupon
        reward = website.sudo().journey_welcome_program_id.filtered('active').reward_ids.filtered(
            lambda r: r.reward_type == 'discount' and r.discount_mode == 'percent')[:1]
        if not reward:
            return 0.0
        base, _above = self._journey_discount_base()
        return self.currency_id.round(base * reward.discount / 100.0)

    def _journey_summary(self, website):
        """Everything the order page shows about the amounts."""
        self.ensure_one()
        currency = self.currency_id
        items = self._journey_items_amount()
        threshold = self._journey_free_threshold()
        delivery_lines = self.order_line.filtered('is_delivery')
        has_delivery = bool(self.carrier_id and delivery_lines)
        delivery_fee = sum(delivery_lines.mapped('price_total'))
        free_delivery = has_delivery and threshold is not None and currency.is_zero(delivery_fee) \
            and currency.compare_amounts(items, threshold) >= 0
        base_fee = self._journey_delivery_base_fee() if free_delivery else 0.0

        coupons = []
        for line in self.order_line.filtered(
                lambda l: l.is_reward_line and l.reward_id.reward_type == 'discount' and l.price_total < 0):
            reward = line.reward_id
            code_based = line.coupon_id in self.applied_coupon_ids or reward.program_id.trigger == 'with_code'
            coupons.append({
                'line': line,
                'name': line.name.split('\n')[0],
                'amount': -line.price_total,
                'code': line.coupon_id.code if line.coupon_id in self.applied_coupon_ids else '',
                'removable': code_based,
                'message': self._journey_coupon_message(reward),
            })
        discount = sum(c['amount'] for c in coupons)
        left = max(threshold - items, 0.0) if threshold is not None else 0.0
        return {
            'items_count': int(sum(self._journey_product_lines().mapped('product_uom_qty'))),
            'items_amount': items,
            'threshold': threshold,
            'left_for_free': left,
            'progress': 100 if threshold is None or not threshold else min(100, int(items / threshold * 100)),
            'has_delivery': has_delivery,
            'delivery_fee': delivery_fee,
            'free_delivery': free_delivery,
            'delivery_base_fee': base_fee,
            'coupons': coupons,
            'discount': discount,
            'savings': discount + base_fee,
            'total': self.amount_total,
            'signup_saving': self._journey_signup_saving(website),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # After the order (Annex 3 v2 §4, C6)
    # ──────────────────────────────────────────────────────────────────────────

    def _journey_signup_state(self):
        """What the confirmation page offers the guest who placed this order:
        'offer' (create an account in one tap), 'has_account' (the email of
        the order already has one: sign in; linking the guest order to it is
        out of scope) or False (nothing)."""
        self.ensure_one()
        partner = self.partner_id
        email = partner.email_normalized
        if not (self.website_id.journey_enabled and email) or partner == self.website_id.user_id.partner_id:
            return False
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        if partner.with_context(active_test=False).user_ids:
            return False
        if Users.search_count([('login', '=ilike', email), ('active', '=', True)], limit=1):
            return 'has_account'
        if Users.search_count([('login', '=ilike', email)], limit=1) or Users._get_signup_invitation_scope() != 'b2c':
            return False
        return 'offer'

    def _journey_can_sign_up(self):
        return self._journey_signup_state() == 'offer'

    def _journey_sign_up(self):
        """Create the customer's account on the order's own contact (so the
        order is in My orders) and email the link to choose a password. The
        welcome coupon is given at the account creation (res.users)."""
        self.ensure_one()
        partner = self.partner_id
        user = self.env['res.users'].sudo()._signup_create_user({
            'login': partner.email_normalized,
            'partner_id': partner.id,
        })
        try:
            user.with_context(create_user=True)._action_reset_password(signup_type='signup')
        except MailDeliveryException:
            # The account stays: "Reset password" on the sign-in page sends the link again
            _logger.warning("Password link not sent to the new customer %s", user.login)
        return user

    def _journey_next_order_coupon(self):
        """Coupon this order earns for the next one (a "Next Order Coupons"
        program), for the confirmation page: {'title', 'code', 'ready'} or None.
        The coupon is made with the cart; its point is given when the order is
        confirmed (paid)."""
        self.ensure_one()
        entry = self.sudo().coupon_point_ids.filtered(
            lambda p: p.points > 0 and p.coupon_id.program_id.program_type == 'next_order_coupons')[:1]
        if not entry:
            return None
        coupon = entry.coupon_id
        program = coupon.program_id
        return {
            'title': program.reward_ids[:1].description or program.name,
            'code': coupon.code,
            'ready': self.state == 'sale',
        }

    def _journey_track_stage(self):
        """Stage shown in the tracking bar (Online Orders stage)."""
        self.ensure_one()
        stage = self.sudo().stage_id
        return stage.portal_label or stage.name

    def _journey_track_url(self):
        """Track / View details page (guests: with the order's access token)."""
        url = '/my/orders/%s/track' % self.id
        if self.env.user._is_public() and self.access_token:
            url += '?access_token=%s' % self.access_token
        return url

    def _journey_track_step(self):
        """Step of the order status: 0 received, 1 out for delivery, 2 delivered
        (from the Online Orders stage), -1 cancelled."""
        self.ensure_one()
        stage = self.sudo().stage_id
        if self.state == 'cancel' or stage.code == 'cancelled':
            return -1
        Stage = self.env['online.order.stage'].sudo()
        for step, code in ((2, 'delivered'), (1, 'out_for_delivery')):
            reference = Stage._get_by_code(code)
            if stage and reference and stage._is_at_or_after(reference):
                return step
        return 0
