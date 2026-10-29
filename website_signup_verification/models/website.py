from odoo import _, api, fields, models


class Website(models.Model):
    _inherit = 'website'

    signup_verification = fields.Boolean(
        string='Verify Sign-ups with a Code',
        default=True,
        help='Sign-up sends a code to the email and creates the account only once it is entered; '
             'a guest email is linked to its existing customer. Untick to go back to the standard sign-up.',
    )
    login_social_first = fields.Boolean(
        string='Google and Facebook First on Sign-in',
        default=True,
        help='Sign-in and sign-up pages: the Google and Facebook buttons at the top, then the email form '
             '(shorter page). Untick to go back to the standard pages.',
    )
    signup_coupon_program_id = fields.Many2one(
        'loyalty.program',
        string='Sign-up Coupon',
        domain=[('program_type', '=', 'promo_code')],
        help='Promo code programme with a fixed code: applied after signing up, only for accounts '
             'activated by the code (or Google / Facebook), once per customer and per mobile number. '
             'Its discount and minimum are shown on the order page. Empty: no sign-up coupon rules.',
    )

    def _signup_coupon_program(self):
        """The active sign-up coupon programme (empty when none or archived)."""
        self.ensure_one()
        # sudo: website visitors cannot read the loyalty programs
        return self.sudo().signup_coupon_program_id.filtered('active')

    def _journey_welcome_program(self):
        """One sign-up offer: with a sign-up coupon, no welcome coupon as well."""
        if self._signup_coupon_program():
            return self.env['loyalty.program']
        return super()._journey_welcome_program()

    def _journey_signup_offer(self):
        return self._signup_coupon_program() or super()._journey_signup_offer()

    def _signup_coupon_code(self):
        rule = self._signup_coupon_program().rule_ids.filtered(lambda r: r.mode == 'with_code' and r.code)
        return rule[:1].code or ''

    def _signup_coupon_reward(self):
        """Percentage discount of the sign-up coupon (empty when it gives something else)."""
        return self._signup_coupon_program().reward_ids.filtered(
            lambda r: r.reward_type == 'discount' and r.discount_mode == 'percent')[:1]

    def _signup_coupon_title(self):
        """'Sign up and get 10% off' at the rate of the programme ('' without a percentage)."""
        reward = self._signup_coupon_reward()
        if not reward:
            return ''
        return _("New here? Sign up and get %s%% off", '%g' % reward.discount)

    @api.model
    def _signup_set_default_coupon_program(self):
        program = self.env.ref('website_signup_verification.loyalty_program_signup_coupon', raise_if_not_found=False)
        if program:
            self.search([('signup_coupon_program_id', '=', False)]).signup_coupon_program_id = program
