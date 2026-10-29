from odoo import api, fields, models

BRAND_LAYOUT = 'website_brand_emails.mail_layout'


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    brand_email = fields.Boolean(
        "The Cut design", readonly=True,
        help="Sent in The Cut design (header with the logo, footer of the website).")
    brand_original_id = fields.Many2one(
        'mail.template', "The Cut version of", readonly=True, ondelete='set null',
        help="Sent instead of this standard email to website customers.")

    def _brand_version(self, res_id):
        """The Cut version of this email for this record, if it gets one.

        :return: (template to send, website) — website empty: the standard email
        """
        self.ensure_one()
        website = self.env['website']
        if not res_id or not self.model:
            return self, website
        brand = self if self.brand_email else self.sudo().search(
            [('brand_original_id', '=', self.id)], limit=1).with_env(self.env)
        if not brand:
            return self, website
        website = website.sudo()._brand_website_for(self.env[self.model].browse(res_id).exists())
        return (brand, website) if website else (self, website)

    def _brand_email_from(self, website):
        """Sender of a The Cut email without its own sender: no-reply@, or the
        order emails address for the coupons."""
        if self.model == 'loyalty.card':
            return website._brand_orders_from()
        return website._brand_noreply_from()

    def send_mail(self, res_id, force_send=False, raise_exception=False, email_values=None,
                  email_layout_xmlid=False):
        template, website = self._brand_version(res_id)
        if website:
            email_values = dict(email_values or {})
            if not template.email_from:
                email_values['email_from'] = template._brand_email_from(website)
            email_layout_xmlid = BRAND_LAYOUT
        return super(MailTemplate, template).send_mail(
            res_id, force_send=force_send, raise_exception=raise_exception,
            email_values=email_values, email_layout_xmlid=email_layout_xmlid)
