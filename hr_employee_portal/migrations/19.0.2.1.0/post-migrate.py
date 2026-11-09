from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # Before 19.0.2.1.0 the portal offered every leave type. It now offers
    # only the types ticked "Available in Employee Portal": tick the ones the
    # company already uses so the request form is not empty after upgrade.
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.leave.type']._ep_enable_used_types()
