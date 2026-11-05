import re
from urllib.parse import urlsplit

from odoo import api, fields, models
from odoo.tools import float_is_zero, format_date

DEFAULT_HOMEPAGE_DESCRIPTION = "This is the homepage of the website"
# Homepage in Google and in link previews (BRD 3.7): no numbers, so it never goes out of date
HOMEPAGE_TITLE = "The Cut | Premium Wagyu & Venison Delivery in Abu Dhabi"
HOMEPAGE_DESCRIPTION = ("Premium Wagyu beef and venison from Abu Dhabi’s Excellence Meats. "
                        "Same-day chilled delivery in Abu Dhabi. Order online.")
HOMEPAGE_IMAGE = '/website_the_cut_pages/static/src/img/og_home.png'
WEEKDAYS = [
    ('shop_monday', "Monday"), ('shop_tuesday', "Tuesday"), ('shop_wednesday', "Wednesday"),
    ('shop_thursday', "Thursday"), ('shop_friday', "Friday"), ('shop_saturday', "Saturday"),
    ('shop_sunday', "Sunday"),
]


def cut_time(value):
    """19.0 -> '7 PM', 19.5 -> '7:30 PM': the 12-hour format of the pages."""
    hours = int(value)
    minutes = round((value - hours) * 60)
    if minutes == 60:
        hours, minutes = hours + 1, 0
    hours %= 24
    text = str(hours % 12 or 12) + (':%02d' % minutes if minutes else '')
    return '%s %s' % (text, 'AM' if hours < 12 else 'PM')


def cut_hours(value):
    """3.0 -> '3 hours', 1.0 -> '1 hour', 1.5 -> '90 minutes' ('' when not set)."""
    if value <= 0:
        return ''
    if float_is_zero(value % 1, precision_digits=2):
        return '%d hour%s' % (value, '' if int(value) == 1 else 's')
    return '%d minutes' % round(value * 60)


def cut_local_phone(number):
    """'+971 50 717 9729' -> '0507179729': how the pages write UAE numbers."""
    digits = re.sub(r'\D', '', number or '')
    if digits.startswith('00'):
        digits = digits[2:]
    return '0' + digits[3:] if digits.startswith('971') else digits


def cut_phone_link(number):
    """'026393944' or '+971 2 639 3944' -> 'tel:+97126393944' ('' when not set)."""
    local = cut_local_phone(number)
    if not local:
        return ''
    return 'tel:' + ('+971' + local[1:] if local.startswith('0') else '+' + local)


class Website(models.Model):
    _inherit = 'website'

    cut_pages_enabled = fields.Boolean(
        "The Cut pages",
        help="The homepage, Delivery & Pickup, Privacy Policy, Terms of Sale and About Us of The Cut, "
             "and its header and footer on every page. Untick to go back to the previous pages at once.")
    cut_care_email = fields.Char(
        "Customer care email", help="Contact email of the Privacy Policy. Empty: the line is hidden.")
    cut_retention_period = fields.Char(
        "Data retention period",
        help='How long account and order data is kept for accounting, tax and legal purposes, '
             'e.g. "5 years" (Privacy Policy). Empty: no period is given.')
    cut_policies_date = fields.Date(
        "Policies last updated", help="Shown on the Privacy Policy and the Terms of Sale. Empty: not shown.")
    cut_damaged_box_note = fields.Boolean(
        "Damaged packaging line",
        help='Delivery & Pickup and Terms of Sale: ask customers to tell us when the box arrives damaged.')

    # ──────────────────────────────────────────────────────────────────────────
    # Values of the pages (BRD 3.5): one source each, '' when not set (the
    # sentence that contains it is then hidden)
    # ──────────────────────────────────────────────────────────────────────────

    def _cut_delivery_methods(self):
        """Delivery methods of the shop, in their order: the rows of "Where we deliver"."""
        self.ensure_one()
        return self.env['delivery.carrier'].sudo().search([
            ('is_published', '=', True),
            ('website_id', 'in', (False, self.id)),
            ('company_id', 'in', (False, self.company_id.id)),
        ], order='sequence, id')

    def _cut_amount(self, amount):
        """400.0 -> 'AED 400', 40.01 -> 'AED 40.01'."""
        currency = self.company_id.currency_id
        amount = currency.round(amount)
        digits = 0 if float_is_zero(amount % 1, precision_digits=currency.decimal_places) else currency.decimal_places
        return '%s %s' % (currency.name, f'{amount:,.{digits}f}')

    def _cut_delivery_price(self, method):
        """Price of a fixed-price method as the checkout shows it (with VAT on a shop showing
        prices with taxes); None for other kinds, which the checkout computes."""
        if not method or method.delivery_type != 'fixed':
            return None
        price = method.fixed_price
        taxes = method.product_id.taxes_id._filter_taxes_by_company(self.company_id)
        if taxes and self.show_line_subtotals_tax_selection == 'tax_included':
            price = taxes.compute_all(
                price, currency=self.company_id.currency_id, product=method.product_id)['total_included']
        return price

    def _cut_fee(self, method):
        """'AED 40' ('' when free or not a fixed price)."""
        price = self._cut_delivery_price(method)
        if price is None or self.company_id.currency_id.is_zero(price):
            return ''
        return self._cut_amount(price)

    def _cut_free_above(self, method):
        """'AED 400': free delivery above this amount ('' when not set)."""
        if not method or not method.free_over or method.amount <= 0:
            return ''
        return self._cut_amount(method.amount)

    def _cut_delivery_row(self, method):
        """A row of "Where we deliver"."""
        price = self._cut_delivery_price(method)
        always_free = price is not None and self.company_id.currency_id.is_zero(price)
        cutoff = cut_time(method.promise_same_day_cutoff)
        if method.enable_same_day_delivery:
            hours = cut_hours(method.promise_same_day_hours)
            detail = ("Orders before %s" % cutoff if method.cut_area == 'pickup' or not hours
                      else "Within %s, orders before %s" % (hours, cutoff))
        else:
            start = method.promise_next_day_from
            detail = ("In the morning" if start < 12 else "In the afternoon" if start < 17 else "In the evening")
        free_above = self._cut_free_above(method)
        return {
            'name': method.cut_website_name or method.name,
            'note': method.cut_website_note or '',
            'same_day': method.enable_same_day_delivery,
            'detail': detail,
            'fee': "Free" if always_free else (self._cut_amount(price) if price is not None else ''),
            'free': "ALWAYS FREE" if always_free else ("FREE ABOVE %s" % free_above if free_above else ''),
        }

    def _cut_contact(self):
        """Contact details of the footer, the Terms and the Privacy Policy."""
        self.ensure_one()
        partner = self.company_id.sudo().partner_id
        return {
            'domain': urlsplit(self.get_base_url()).netloc,
            'whatsapp': cut_local_phone(self.journey_whatsapp_number),
            'whatsapp_url': self._journey_whatsapp_url(),
            'phone': cut_local_phone(partner.phone),
            'phone_url': cut_phone_link(partner.phone),
            'address': ', '.join(filter(None, [partner.street, partner.street2, partner.city])),
        }

    def _cut_same_day_method(self, methods=None):
        """The Abu Dhabi method with same-day delivery: its cut-off time is the one of the site."""
        methods = self._cut_delivery_methods() if methods is None else methods
        return methods.filtered(lambda m: m.cut_area == 'abu_dhabi' and m.enable_same_day_delivery)[:1]

    def _cut_product_delivery_line(self):
        """Line of the product page (Annex 3B, 3.1): same-day delivery and free pickup,
        from the delivery methods ('' when neither is offered)."""
        self.ensure_one()
        methods = self._cut_delivery_methods()
        parts = []
        same_day = self._cut_same_day_method(methods)
        if same_day:
            parts.append("Same-day delivery in Abu Dhabi for orders before %s" % cut_time(same_day.promise_same_day_cutoff))
        pickup = methods.filtered(lambda m: m.cut_area == 'pickup')[:1]
        price = self._cut_delivery_price(pickup)
        if price is not None and self.company_id.currency_id.is_zero(price):
            parts.append("Free pickup from our shop")
        return ' · '.join(parts)

    def _journey_location_values(self):
        # "Deliver to" bar, before the customer sets a location: the cut-off time of the delivery method
        values = super()._journey_location_values()
        if self.cut_pages_enabled and not values['has_location']:
            method = self._cut_same_day_method()
            if method:
                # "7 PM" stays on one line
                values['message'] = "Same-day delivery in Abu Dhabi for orders before %s" % cut_time(
                    method.promise_same_day_cutoff).replace(' ', '\N{NO-BREAK SPACE}')
        return values

    def _cut_values(self):
        """Everything of the pages that can change, read from the settings."""
        self.ensure_one()
        methods = self._cut_delivery_methods()
        abu_dhabi = self._cut_same_day_method(methods)
        uae = methods.filtered(lambda m: m.cut_area == 'uae')[:1]
        pickup = methods.filtered(lambda m: m.cut_area == 'pickup')[:1]
        store = self.env['store.settings'].sudo()._find_for_website(self)
        opening = closing = ''
        if store and store.shop_opening_time < store.shop_closing_time:
            opening, closing = cut_time(store.shop_opening_time), cut_time(store.shop_closing_time)
        days = [name for fname, name in WEEKDAYS if store[fname]] if store else []
        pickup_price = self._cut_delivery_price(pickup)
        return {
            **self._cut_contact(),
            'cutoff': cut_time(abu_dhabi.promise_same_day_cutoff) if abu_dhabi else '',
            'same_day_hours': cut_hours(abu_dhabi.promise_same_day_hours) if abu_dhabi else '',
            'abu_dhabi_fee': self._cut_fee(abu_dhabi),
            'abu_dhabi_free': self._cut_free_above(abu_dhabi),
            'uae_fee': self._cut_fee(uae),
            'uae_free': self._cut_free_above(uae),
            'pickup_free': pickup_price is not None and self.company_id.currency_id.is_zero(pickup_price),
            'opening': opening,
            'closing': closing,
            'open_days': "every day" if len(days) == 7 else ', '.join(days),
            'rows': [self._cut_delivery_row(method) for method in methods],
            'care_email': self.cut_care_email or '',
            'retention': self.cut_retention_period or '',
            'policies_date': format_date(self.env, self.cut_policies_date, date_format='d MMMM y')
            if self.cut_policies_date else '',
            'damaged_box_note': self.cut_damaged_box_note,
        }

    @api.model
    def _cut_set_homepage_seo(self):
        """Install: title, description and image of the homepage in Google and link
        previews (BRD 3.7), unless someone already wrote them."""
        for page in self.env['website.page'].search([('url', '=', '/')]):
            if page.website_meta_description and page.website_meta_description != DEFAULT_HOMEPAGE_DESCRIPTION:
                continue
            page.write({
                'website_meta_title': HOMEPAGE_TITLE,
                'website_meta_description': HOMEPAGE_DESCRIPTION,
                'website_meta_og_img': page.website_meta_og_img or HOMEPAGE_IMAGE,
            })
