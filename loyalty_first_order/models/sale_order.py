from odoo import _, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.http import request

# 'delivered' is added to sale.order.state by em_custom; it is still a confirmed order.
CONFIRMED_STATES = ('sale', 'delivered')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _is_first_order(self):
        """True if the customer has no confirmed order other than this one.

        - Guest cart (website public user): False. We cannot know yet whether the
          guest already ordered, so the offer is not applied in the cart (a note
          is shown instead). It is applied once the guest enters name / email
          at checkout and turns out to be a new customer.
        - Matching is done on the contact AND on the email, because every guest
          checkout creates a new contact in Odoo.
        """
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        if not partner:
            return False
        public_partner = self.website_id.user_id.partner_id if self.website_id else False
        if public_partner and partner == public_partner:
            return False

        partner_domain = [('partner_id', 'child_of', partner.id)]
        email = (partner.email or self.partner_id.email or '').strip()
        if email:
            partner_domain = ['|', ('partner_id.email', '=ilike', email)] + partner_domain
        return not self.env['sale.order'].sudo().search_count([
            ('state', 'in', CONFIRMED_STATES),  # only confirmed orders count
            ('id', '!=', self.id),
        ] + partner_domain, limit=1)

    def _program_check_compute_points(self, programs):
        result = super()._program_check_compute_points(programs)
        if self.env.context.get('skip_first_order_check'):
            return result
        restricted = programs.filtered('first_order_only')
        if restricted and not self._is_first_order():
            for program in restricted:
                result[program] = {'error': _("This promotion is only valid on your first order.")}
        return result

    def _get_first_order_reward_programs(self):
        """First-order promotions applied on this order. A next-order coupon is not
        one: only earning it is limited to the first order, not using it."""
        self.ensure_one()
        return self.order_line.reward_id.program_id.filtered(
            lambda p: p.first_order_only and p.applies_on != 'future')

    def _update_programs_and_rewards(self):
        programs_before = {order: order._get_first_order_reward_programs() for order in self}
        res = super()._update_programs_and_rewards()
        if request and hasattr(request, 'website'):
            # Tell the website customer why the total changed instead of silently
            # dropping the welcome offer (e.g. an email of a returning customer).
            for order, programs in programs_before.items():
                removed = programs - order._get_first_order_reward_programs()
                if order.website_id and removed and not order._is_first_order():
                    request.session['error_promo_code'] = _(
                        "The offer \"%s\" was removed: it is only valid on a first order "
                        "and we found a previous order for this customer.",
                        ", ".join(removed.mapped('name')))
        return res

    def _get_pending_first_order_programs(self):
        """First-order programs a guest cart would get once the customer turns out
        to be new. Used to show a note in the cart instead of the discount."""
        self.ensure_one()
        Program = self.env['loyalty.program']
        if not self.website_id or not self._is_anonymous_cart():
            return Program
        programs = Program.search(Domain.AND([self._get_program_domain(), [
            ('first_order_only', '=', True),
            ('trigger', '=', 'auto'),
            ('applies_on', '!=', 'future'),
        ]]))
        if not programs:
            return Program
        status = self.with_context(skip_first_order_check=True)._program_check_compute_points(programs)
        return programs.filtered(lambda p: 'error' not in status.get(p, {}))

    def _get_offer_summary_lines(self):
        """Offer lines (discounts, free shipping, gift cards) shown as their own
        rows in the order summary instead of among the cart items. Free product
        rewards stay with the items: they are real products."""
        self.ensure_one()
        return self.website_order_line.filtered(
            lambda l: l.is_reward_line
            and l.reward_id.reward_type != 'product'
            and not self.currency_id.is_zero(l._get_cart_display_price()))

    def _get_items_summary_amount(self):
        """Items total before offers, with the same tax display as the cart lines."""
        self.ensure_one()
        items = self.website_order_line - self._get_offer_summary_lines()
        return sum(line._get_cart_display_price() for line in items)

    def action_confirm(self):
        # Safety net for backend orders only. Website orders are confirmed after
        # the online payment, so blocking there would leave a paid, unconfirmed
        # order; their rewards are already re-checked before the payment step.
        for order in self.filtered(lambda o: not o.website_id):
            if order._get_first_order_reward_programs() and not order._is_first_order():
                raise UserError(_(
                    "Order %s contains a first-order promotion, but the customer "
                    "already has a confirmed order. Please update the rewards first.",
                    order.name))
        return super().action_confirm()
