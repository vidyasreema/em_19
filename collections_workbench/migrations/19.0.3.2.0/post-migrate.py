from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Fill the new "Thank-you due" flag once, instead of waiting for the night."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.partner']._cron_collection_daily()
