from odoo import fields, models


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    # How the method is shown on the website pages (no effect on the delivery itself)
    cut_website_name = fields.Char(
        "Name on the Website", translate=True,
        help='Row of the "Where we deliver" table, e.g. "Abu Dhabi Island". Empty: the name of the method.')
    cut_website_note = fields.Char(
        "Note on the Website", translate=True,
        help='Small line under the name, e.g. "For example Masdar City" or "Mushrif Mall".')
    cut_area = fields.Selection(
        [('abu_dhabi', "Abu Dhabi"), ('uae', "Rest of the UAE"), ('pickup', "Pickup from the shop")],
        string="Area on the Website",
        help="Which promise of the pages this method gives: the first Abu Dhabi method with same-day "
             "delivery gives the order cutoff, delivery time, fee and free-delivery amount of the "
             "homepage; the first Rest of the UAE method the fee and amount for the rest of the UAE.")
