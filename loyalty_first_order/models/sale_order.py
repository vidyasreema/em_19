from odoo import _, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _is_first_order(self):
        """True if the customer has no confirmed order other than this one.

        - Guest cart (website public user): True, so the offer is shown in the
          cart. It is checked again once the guest enters name / email.
        - Matching is done on the contact AND on the email, because every guest
          checkout creates a new contact in Odoo.
        """
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        if not partner:
            return False
        public_partner = self.website_id.user_id.partner_id if self.website_id else False
        if public_partner and partner == public_partner:
            return True

        partner_domain = [('partner_id', 'child_of', partner.id)]
        email = (partner.email or self.partner_id.email or '').strip()
        if email:
            partner_domain = ['|', ('partner_id.email', '=ilike', email)] + partner_domain
        return not self.env['sale.order'].sudo().search_count([
            ('state', '=', 'sale'),          # only confirmed orders count
            ('id', '!=', self.id),
        ] + partner_domain, limit=1)

    def _program_check_compute_points(self, programs):
        result = super()._program_check_compute_points(programs)
        restricted = programs.filtered('first_order_only')
        if restricted and not self._is_first_order():
            for program in restricted:
                result[program] = {'error': _("This promotion is only valid on your first order.")}
        return result

    def action_confirm(self):
        # Safety net for backend orders only. Website orders are confirmed after
        # the online payment, so blocking there would leave a paid, unconfirmed
        # order; their rewards are already re-checked before the payment step.
        for order in self.filtered(lambda o: not o.website_id):
            first_order_rewards = order.order_line.filtered(
                lambda l: l.reward_id and l.reward_id.program_id.first_order_only)
            if first_order_rewards and not order._is_first_order():
                raise UserError(_(
                    "Order %s contains a first-order promotion, but the customer "
                    "already has a confirmed order. Please update the rewards first.",
                    order.name))
        return super().action_confirm()
