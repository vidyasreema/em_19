from odoo import _, api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ──────────────────────────────────────────────────────────────────────────
    # Shown: the short code instead of the long one
    # ──────────────────────────────────────────────────────────────────────────

    def _journey_summary(self, website):
        values = super()._journey_summary(website)
        for coupon in values.get('coupons', []):
            card = coupon['line'].coupon_id
            if coupon.get('code') and card:
                coupon['code'] = card._short_code_display()
        return values

    def _journey_next_order_coupon(self):
        values = super()._journey_next_order_coupon()
        if values:
            entry = self.sudo().coupon_point_ids.filtered(
                lambda p: p.points > 0 and p.coupon_id.program_id.program_type == 'next_order_coupons')[:1]
            values['code'] = entry.coupon_id._short_code_display()
        return values

    @api.depends('online_coupon_held')
    def _compute_online_next_order_coupons(self):
        # Delivered email and tracking page: the short code (once, even for several coupons)
        super()._compute_online_next_order_coupons()
        for order in self.filtered('online_next_order_coupons'):
            codes = order._online_next_order_coupon_points().coupon_id.mapped(lambda c: c._short_code_display())
            order.online_next_order_coupons = ', '.join(dict.fromkeys(codes))

    # ──────────────────────────────────────────────────────────────────────────
    # Typed: the short code applies the customer's own coupon of the programme
    # ──────────────────────────────────────────────────────────────────────────

    def _try_apply_code(self, code):
        program = self.env['loyalty.program']._short_code_program(code)
        if not program:
            return super()._try_apply_code(code)
        coupon = self._short_code_coupon(program)
        if not coupon:
            return {'error': _("You don't have this coupon.")}
        return super()._try_apply_code(coupon.code)

    def _short_code_coupon(self, program):
        """The coupon of this customer for the programme: a usable one (the one that
        expires first), else one waiting for its order's delivery (its message says
        when it can be used). Guests have none: the coupons are for accounts."""
        self.ensure_one()
        partner = self.partner_id
        if not partner or partner.is_public or partner == self.website_id.sudo().user_id.partner_id:
            return self.env['loyalty.card']
        today = fields.Date.context_today(self)
        if program.date_to and program.date_to < today:
            return self.env['loyalty.card']
        cards = self.env['loyalty.card'].sudo().search([
            ('program_id', '=', program.id),
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
            '|', ('expiration_date', '=', False), ('expiration_date', '>=', today),
        ], order='expiration_date asc, id asc')
        required = min(program.reward_ids.mapped('required_points') or [1])
        usable = cards.filtered(lambda c: c.points >= required)
        return usable[:1] or cards.filtered(lambda c: c.order_id.online_coupon_held)[:1]
