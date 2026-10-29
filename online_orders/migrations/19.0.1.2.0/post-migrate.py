import logging

_logger = logging.getLogger(__name__)

# The order emails take their sender from the website setting "Order emails from"
# (company email when empty). Templates edited by hand are left as they are.
SENDERS = {
    'mail_template_out_for_delivery': (
        "{{ (object.company_id.email_formatted or user.email_formatted) }}",
        "{{ (object.website_id.online_orders_email_from or object.company_id.email_formatted or user.email_formatted) }}",
    ),
    'mail_template_delivered': (
        "{{ (object.company_id.email_formatted or user.email_formatted) }}",
        "{{ (object.website_id.online_orders_email_from or object.company_id.email_formatted or user.email_formatted) }}",
    ),
    'mail_template_cancelled': (
        "{{ (object.company_id.email_formatted or user.email_formatted) }}",
        "{{ (object.website_id.online_orders_email_from or object.company_id.email_formatted or user.email_formatted) }}",
    ),
    'mail_template_address_updated': (
        "{{ (object.company_id.email_formatted or user.company_id.email_formatted or user.email_formatted) }}",
        "{{ (ctx.get('online_orders_email_from') or object.company_id.email_formatted "
        "or user.company_id.email_formatted or user.email_formatted) }}",
    ),
}


def migrate(cr, version):
    for xmlid, (old, new) in SENDERS.items():
        cr.execute("""
            UPDATE mail_template t
               SET email_from = %s
              FROM ir_model_data d
             WHERE d.module = 'online_orders' AND d.name = %s
               AND d.model = 'mail.template' AND d.res_id = t.id
               AND t.email_from = %s
        """, (new, xmlid, old))
        _logger.info("Sender of %s: %s", xmlid, "updated" if cr.rowcount else "kept (edited by hand)")
