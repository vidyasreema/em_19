from odoo import fields, models


class Website(models.Model):
    _inherit = 'website'

    order_source_question = fields.Boolean(
        string='Ask How Customers Heard About Us',
        default=True,
        help='After placing an order, the confirmation page asks "How did you hear about us?". '
             'The answer is saved on the order and in its history.',
    )
