from odoo import fields, models


class Website(models.Model):
    _inherit = 'website'

    my_account_page = fields.Boolean(
        string='App-style My Account Page',
        default=True,
        help='My Account (/my) as one column of cards: profile, orders, coupons, settings and help. '
             'Untick to go back to the standard page.',
    )
