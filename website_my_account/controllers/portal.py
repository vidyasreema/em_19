from odoo import _
from odoo.http import request, route

from odoo.addons.sale.controllers.portal import CustomerPortal


class MyAccountPortal(CustomerPortal):

    @route()
    def home(self, **kw):
        """My Account in the style of shopping apps (one column of cards)."""
        if not request.website.my_account_page:
            return super().home(**kw)
        values = self._prepare_portal_layout_values()
        values.update(self._prepare_home_portal_values(['order_count', 'invoice_count', 'ticket_count']))
        values.update(self._my_account_values())
        return request.render('website_my_account.my_home', values)

    def _prepare_my_account_rendering_values(self, *args, **kwargs):
        """Account details (Edit) of a home customer: no company name, VAT,
        or how to receive invoices (business fields)."""
        values = super()._prepare_my_account_rendering_values(*args, **kwargs)
        if request.website.my_account_page:
            values.update(my_account_simple=True, invoice_sending_methods={}, invoice_edi_formats={})
        return values

    def _prepare_address_form_values(self, *args, **kwargs):
        """Addresses (Add / Edit) of a home customer: no company name and VAT either."""
        values = super()._prepare_address_form_values(*args, **kwargs)
        if request.website.my_account_page:
            values['my_account_simple'] = True
        return values

    def _my_account_values(self):
        website = request.website
        partner = request.env.user.partner_id
        journey = website.journey_enabled

        last_order = request.env['sale.order'].search(
            self._prepare_orders_domain(partner), order='date_order desc, id desc', limit=1)
        coupon_count = 0
        if journey:
            current, _past = request.env['loyalty.card']._journey_portal_coupons(partner, cart=request.cart)
            coupon_count = len([coupon for coupon in current if coupon['state'] == 'current'])

        status = ''
        if last_order:
            status = {
                -1: _("Cancelled"), 0: _("Received"), 1: _("Out for delivery"), 2: _("Delivered"),
            }.get(last_order._journey_track_step(), '')

        languages = website.language_ids
        language = languages.filtered(lambda lang: lang.code == request.lang.code)[:1]
        other_language = (languages - language)[:1]

        return {
            'partner': partner,
            'profile': partner._my_account_profile(),
            'last_order': last_order,
            'last_order_status': status,
            'coupons_enabled': journey,
            'coupon_count': coupon_count,
            'saved': partner._journey_lifetime_savings(website) if journey else 0.0,
            'favourite_count': len(request.env['product.wishlist'].current()),
            'language': language,
            'language_url': other_language and '/website/lang/%s?r=/my' % other_language.url_code,
            'whatsapp_url': website._journey_whatsapp_url(_("Hello, I need help with my account")),
        }
