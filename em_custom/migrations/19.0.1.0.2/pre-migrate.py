def migrate(cr, version):
    cr.execute("UPDATE sale_order SET state = 'sale' WHERE state = 'delivered'")
    cr.execute("UPDATE sale_order_line SET state = 'sale' WHERE state = 'delivered'")