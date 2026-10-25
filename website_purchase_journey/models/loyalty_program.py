from odoo import models


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    def _journey_give_welcome_coupon(self, partner):
        """One welcome coupon per customer (it appears in the customer's coupons)."""
        self.ensure_one()
        Card = self.env['loyalty.card'].sudo()
        if Card.search_count([('program_id', '=', self.id), ('partner_id', '=', partner.id)]):
            return Card
        return Card.create({
            'program_id': self.id,
            'partner_id': partner.id,
            'points': max(self.reward_ids.mapped('required_points') or [1]),
        })
