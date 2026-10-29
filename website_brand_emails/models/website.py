import base64
from email.utils import formataddr

from odoo import api, fields, models
from odoo.tools.mimetypes import guess_mimetype

# The customer emails of these records take The Cut design (others keep the standard one)
BRAND_MODELS = ('sale.order', 'res.users', 'res.partner', 'loyalty.card')


class Website(models.Model):
    _inherit = 'website'

    brand_emails = fields.Boolean(
        "The Cut design for customer emails", default=True,
        help="Order, account and coupon emails of website customers get the design of this "
             "website. Untick to go back to the standard emails at once.")
    brand_email_logo = fields.Image(
        "Email logo", max_width=600, max_height=200,
        help="Logo at the top of the customer emails, as PNG or JPG: email apps (Gmail, Outlook) "
             "do not show SVG images. Empty: the website logo when it is not an SVG, else the "
             "name of the website.")

    @api.model
    def _brand_website_for(self, record):
        """Website whose design the customer email of this record takes.

        :return: the website, empty for the standard email (wholesale orders,
            employees, coupons of programmes not on the website)
        """
        record = record.sudo()[:1]
        if not record or record._name not in BRAND_MODELS:
            return self.browse()
        website = self.browse()
        if record._name == 'sale.order':
            if not record.website_id:
                return self.browse()  # wholesale order of the sales team
            website = record.website_id
        elif record._name == 'res.users':
            if not record.share:
                return self.browse()  # employee
            website = record.website_id
        elif record._name == 'loyalty.card':
            if not record.program_id.ecommerce_ok:
                return self.browse()
            website = record.program_id.website_id
        if not website:
            company = record.company_id if 'company_id' in record._fields else self.env.company
            website = self.sudo().search([('company_id', '=', (company or self.env.company).id)], limit=1)
        return website.filtered('brand_emails')

    def _brand_noreply_from(self):
        """'The Cut <no-reply@thecutuae.com>' (no-reply@ of the email domain)."""
        self.ensure_one()
        domain = self.company_id.alias_domain_id.name
        return formataddr((self.name, 'no-reply@%s' % domain)) if domain else self.company_id.email_formatted

    def _brand_orders_from(self):
        """Sender of the order emails: "Order emails from", with the name of the
        website (the company email when empty, like the standard emails)."""
        self.ensure_one()
        email = self.online_orders_email_from
        if not email:
            return self.company_id.email_formatted
        return email if '<' in email else formataddr((self.name, email.strip()))

    def _brand_logo_url(self):
        """Logo of the emails ('' when there is none an email app can show)."""
        self.ensure_one()
        if self.brand_email_logo:
            field = 'brand_email_logo'
        elif self.logo and guess_mimetype(base64.b64decode(self.logo)) != 'image/svg+xml':
            field = 'logo'
        else:
            return ''
        return '%s/web/image/website/%s/%s' % (self.get_base_url(), self.id, field)

    def _brand_contact(self):
        """WhatsApp of the shop (the help number of the order page), else the company phone."""
        self.ensure_one()
        whatsapp = self.journey_whatsapp_number if 'journey_whatsapp_number' in self._fields else False
        return whatsapp or self.company_id.phone or ''
