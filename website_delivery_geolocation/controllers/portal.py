from odoo.addons.portal.controllers.portal import CustomerPortal


class CustomerPortalDeliveryAddress(CustomerPortal):

    def _get_mandatory_delivery_address_fields(self, country_sudo):
        """Apartment / villa (street2) is required on delivery addresses, so the
        driver can find the door. Used by the checkout and My Account address
        forms, both for the red required mark and the server-side check."""
        field_names = super()._get_mandatory_delivery_address_fields(country_sudo)
        if self._needs_address():
            field_names.add('street2')
        return field_names
