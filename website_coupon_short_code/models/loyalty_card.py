from odoo import api, models


class LoyaltyCard(models.Model):
    _inherit = 'loyalty.card'

    def _short_code_display(self):
        """The code the customer sees: the programme's short code, else the coupon's own."""
        self.ensure_one()
        return self.program_id.sudo().short_code or self.code

    @api.model
    def _journey_portal_coupons(self, partner, cart=None):
        current, past = super()._journey_portal_coupons(partner, cart=cart)
        for coupon in current + past:
            coupon['code'] = coupon['card']._short_code_display()
        return current, past
