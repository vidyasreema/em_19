from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env['sale.order'].search([
        ('state', '=', 'sale'),
        ('invoice_status', '=', 'no'),
    ])
    lines = orders.order_line
    env.add_to_compute(lines._fields['qty_to_invoice'], lines)
    env.add_to_compute(lines._fields['invoice_status'], lines)
    env.add_to_compute(orders._fields['invoice_status'], orders)
    env.flush_all()