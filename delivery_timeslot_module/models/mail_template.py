# -*- coding: utf-8 -*-
import logging
import re

from markupsafe import Markup

from odoo import api, models

_logger = logging.getLogger(__name__)

PROMISE_MARKER = 'o_delivery_promise_block'
# The promise goes right above the "Ship to" part of the confirmation email. Its
# condition differs between template versions (and their translations), e.g.
# hasattr(object, 'only_services') and ... / object.partner_shipping_id and not object.only_services
INSERT_BEFORE = re.compile(r'<div t-if="[^"]*only_services[^"]*"')
PROMISE_BLOCK = """<div class="o_delivery_promise_block" t-if="object.delivery_promise_message" style="margin: 16px 0px 0px 0px; padding: 12px 16px; background-color: #f6f6f6; border-radius: 6px; color: #454748;">
        <span style="font-weight:bold;">Delivery:</span>
        <t t-out="object.delivery_promise_message or ''">Delivered today within 3 hours</t><br/>
        <span style="font-weight:bold;" t-out="object.delivery_promise_date_label or ''">Wed 21 Oct · by 4:30 PM</span>
    </div>
    """


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    @api.model
    def _timeslot_add_promise_to_confirmation_email(self):
        """Show the delivery promise in the order confirmation email (Annex 3 D3).
        Added once to the standard template, in every installed language (it
        stays editable); a version without the "Ship to" part is left as it is."""
        templates = self.browse()
        for xmlid in ('sale.mail_template_sale_confirmation',):
            templates |= self.env.ref(xmlid, raise_if_not_found=False) or self.browse()
        param = self.env['ir.config_parameter'].sudo().get_param('sale.default_confirmation_template')
        if param and param.isdigit():
            templates |= self.browse(int(param)).exists()
        # English (the source) first, then the translations
        langs = sorted((code for code, _name in self.env['res.lang'].get_installed()), key=lambda c: c != 'en_US')
        for template in templates:
            for lang in langs:
                template_lang = template.with_context(lang=lang)
                # str(): Markup.replace() would escape the block (it must stay HTML)
                body = str(template_lang.body_html or '')
                if PROMISE_MARKER in body:
                    continue
                match = INSERT_BEFORE.search(body)
                if not match:
                    _logger.warning("Delivery promise not added to the email template %s (%s): customized body",
                                    template.name, lang)
                    continue
                template_lang.body_html = Markup(body[:match.start()] + PROMISE_BLOCK + body[match.start():])
                template_lang.invalidate_recordset(['body_html'])
                _logger.info("Delivery promise added to the email template %s (%s)", template.name, lang)
