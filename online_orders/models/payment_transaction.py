from odoo import models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _online_website_transactions(self):
        return self.filtered(lambda tx: tx.sale_order_ids.website_id)

    def _invoice_sale_orders(self):
        # Website orders: no "You have been assigned to Draft Invoice" email to the salesperson
        website_txs = self._online_website_transactions()
        super(PaymentTransaction, website_txs.with_context(mail_auto_subscribe_no_notify=True))._invoice_sale_orders()
        return super(PaymentTransaction, self - website_txs)._invoice_sale_orders()

    def _send_invoice(self):
        # Website orders: the invoice is not emailed at the payment (it stays in Odoo)
        return super(PaymentTransaction, self - self._online_website_transactions())._send_invoice()
