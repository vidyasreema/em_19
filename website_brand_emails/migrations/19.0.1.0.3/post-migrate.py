import logging

from markupsafe import Markup

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# The emails in the brand red of the website (the templates are not updated by an upgrade).
# Only the colour changes: a text edited by hand in Settings is kept.
OLD_RED = '#7A1F2B'
NEW_RED = '#7E1416'
TEMPLATES = [
    'mail_template_order_confirmation', 'mail_template_on_the_way', 'mail_template_delivered',
    'mail_template_cancelled', 'mail_template_address_updated', 'mail_template_account_created',
    'mail_template_set_password', 'mail_template_reset_password', 'mail_template_coupon',
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in TEMPLATES:
        template = env.ref('website_brand_emails.%s' % xmlid, raise_if_not_found=False)
        if not template:
            continue
        for lang, _name in env['res.lang'].get_installed():
            template_lang = template.with_context(lang=lang)
            body = str(template_lang.body_html or '')
            if OLD_RED.lower() not in body.lower():
                continue
            template_lang.body_html = Markup(body.replace(OLD_RED, NEW_RED).replace(OLD_RED.lower(), NEW_RED))
            _logger.info("%s: brand red updated (%s)", xmlid, lang)
