from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _create_user_from_template(self, values):
        """Sign-up (email or Google / Facebook): the welcome coupon is given at
        sign-up, not on the first order (Annex 3 v2, task 4.2)."""
        user = super()._create_user_from_template(values)
        websites = self.env['website'].sudo().search([
            ('journey_enabled', '=', True), ('journey_welcome_program_id', '!=', False)])
        programs = self.env['loyalty.program'].union(*(website._journey_welcome_program() for website in websites))
        for program in programs:
            program._journey_give_welcome_coupon(user.partner_id)
        return user
