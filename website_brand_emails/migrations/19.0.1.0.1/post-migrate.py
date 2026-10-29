import logging

from markupsafe import Markup

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# The Delivered email: "Your order has been delivered" (we deliver meat, not meals).
# A text edited by hand in Settings is left as it is.
OLD = [
    'Delivered. Enjoy your meal!',
    'was delivered. Thank you for choosing us.',
]
NEW = [
    'Your order has been delivered',
    'has been delivered.\n        Thank you for choosing <t t-out="object.website_id.name or object.company_id.name">The Cut</t>!',
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    template = env.ref('website_brand_emails.mail_template_delivered', raise_if_not_found=False)
    if not template:
        return
    for lang, _name in env['res.lang'].get_installed():
        template_lang = template.with_context(lang=lang)
        body = str(template_lang.body_html or '')
        if not all(text in body for text in OLD):
            continue
        for old, new in zip(OLD, NEW):
            body = body.replace(old, new)
        template_lang.body_html = Markup(body)
        _logger.info("Delivered email text updated (%s)", lang)
