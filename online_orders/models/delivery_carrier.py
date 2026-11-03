from odoo import fields, models


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    online_pickup = fields.Boolean(
        'Pickup from the Shop',
        help="Customers collect the order at the shop: the website asks for no delivery address, "
             "and on the Online Orders board the order goes from New straight to Picked up.")

    def _match_address(self, partner):
        # Collected at the shop: the countries / states / zip prefixes of the method do not
        # apply (a guest has no address yet when choosing pickup, Annex 3B, 5.1)
        if self.online_pickup:
            return True
        return super()._match_address(partner)
