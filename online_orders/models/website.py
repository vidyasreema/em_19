from odoo import fields, models


class Website(models.Model):
    _inherit = 'website'

    online_orders_email_from = fields.Char(
        "Order emails from",
        help="Sender of the order emails of this shop (on the way, delivered, cancelled, address "
             "updated), e.g. The Cut <orders@thecutuae.com>. Empty: the email of the company.")

