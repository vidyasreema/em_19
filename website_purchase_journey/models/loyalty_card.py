from odoo import _, api, fields, models
from odoo.tools import format_amount, format_date

# Personal coupons shown in My coupons (promotions and codes for everyone are not)
PERSONAL_PROGRAM_TYPES = ('coupons', 'next_order_coupons')


class LoyaltyCard(models.Model):
    _inherit = 'loyalty.card'

    journey_celebrated = fields.Boolean(
        "New coupon shown", copy=False,
        help="The customer saw the \"You have a new coupon\" popup of My coupons.")

    @api.model
    def _journey_portal_coupons(self, partner, cart=None):
        """Coupons of a customer for My coupons (Annex 3 C5).

        :return: (current, past) lists of dicts; current = ready to use or
            waiting for the payment of the order that earned it
        """
        today = fields.Date.context_today(self)
        cards = self.sudo().search([
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
            ('program_id.program_type', 'in', PERSONAL_PROGRAM_TYPES),
            ('program_id.active', '=', True),
        ], order='create_date desc')
        current, past = [], []
        for card in cards:
            program = card.program_id
            reward = program.reward_ids[:1]
            expiration = card.expiration_date or program.date_to
            earned_on = card.order_id
            if expiration and expiration < today:
                status, state = _("Expired"), 'past'
            elif reward and card.points >= reward.required_points:
                status, state = _("Ready to use"), 'current'
            elif earned_on and earned_on.state == 'sent':
                status, state = _("After payment"), 'waiting'
            elif earned_on and earned_on.state in ('draft', 'cancel'):
                continue  # never earned (cart not paid, or cancelled)
            else:
                status, state = _("Used"), 'past'
            values = {
                'card': card,
                'code': card.code,
                'title': reward.description or program.name,
                'program': program.name,
                'rule': self._journey_coupon_rule(card, expiration),
                'status': status,
                'state': state,
                'applied': bool(cart) and card in cart.applied_coupon_ids,
                'can_apply': state == 'current' and bool(cart and cart.website_order_line),
                'new': state == 'current' and not card.journey_celebrated,
            }
            (past if state == 'past' else current).append(values)
        return current, past

    @api.model
    def _journey_coupon_rule(self, card, expiration):
        """'Members only · one use · no minimum · valid until 30 Nov 2026'"""
        program = card.program_id
        minimum = min(program.rule_ids.mapped('minimum_amount') or [0.0])
        parts = [_("Members only"), _("one use")]
        if minimum:
            currency = program.currency_id or self.env.company.currency_id
            parts.append(_("minimum %s", format_amount(self.env, minimum, currency)))
        else:
            parts.append(_("no minimum"))
        if expiration:
            parts.append(_("valid until %s", format_date(self.env, expiration)))
        return ' · '.join(parts)
