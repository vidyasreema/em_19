import re

from odoo import _, api, fields, models

try:
    import phonenumbers
except ImportError:
    phonenumbers = None

PHONE_CHARACTERS = re.compile(r'^[\d\s()+\-./]+$')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    marketing_consent = fields.Boolean(
        string='News and Offers by Email',
        help='Explicit consent given by the customer at checkout ("Email me with news and offers").',
    )
    marketing_consent_date = fields.Datetime(string='Consent Date', readonly=True)

    def _journey_set_marketing_consent(self, consent):
        for partner in self.filtered(lambda p: p.marketing_consent != bool(consent)):
            partner.write({
                'marketing_consent': bool(consent),
                'marketing_consent_date': fields.Datetime.now(),
            })

    def _journey_lifetime_savings(self, website):
        """Coupons and free delivery on all the customer's confirmed orders of
        the website (Annex 3 C7, shown on the customer card of My Account)."""
        self.ensure_one()
        orders = self.env['sale.order'].sudo().search([
            ('partner_id', 'child_of', self.commercial_partner_id.id),
            ('website_id', '=', website.id),
            ('state', '=', 'sale'),
        ])
        return sum(order._journey_summary(website)['savings'] for order in orders)

    @api.model
    def _journey_check_phone(self, phone, mobile=False):
        """A number typed on the website: a UAE number only, stored in its
        international format (+971 50 123 4567), else an error.
        :param bool mobile: only a mobile number (the receiver of the order)
        :return: tuple (phone, error)"""
        phone = (phone or '').strip()
        if not phone or not phonenumbers:
            return phone, ''
        parsed = None
        if PHONE_CHARACTERS.match(phone):
            digits = re.sub(r'\D', '', phone)
            # "00971 50..." and "971 50..." are typed for "+971 50..."
            candidates = ['+' + digits[2:]] if digits.startswith('00') else [phone, '+' + digits]
            for candidate in candidates:
                try:
                    number = phonenumbers.parse(candidate, 'AE')
                except phonenumbers.NumberParseException:
                    continue
                if phonenumbers.is_valid_number_for_region(number, 'AE'):
                    parsed = number
                    break
        mobile_types = (phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE)
        if parsed and (not mobile or phonenumbers.number_type(parsed) in mobile_types):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL), ''
        if mobile:
            return phone, _("Enter a UAE mobile number, like 050 123 4567.")
        return phone, _("Enter a UAE phone number, like 050 123 4567.")
