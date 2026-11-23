from datetime import date

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class CollectionsCommon(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the accounting test user runs the tests: make it Collections manager
        cls.env.user.write({'group_ids': [(4, cls.env.ref(
            'collections_workbench.group_collection_manager').id)]})
        cls.customer =cls.env['res.partner'].create({'name': 'ACME Collections Test'})
        cls.customer2 = cls.env['res.partner'].create({'name': 'Star Collections Test'})
        cls.cat_promise = cls.env.ref('collections_workbench.note_cat_promise')
        cls.cat_no_answer = cls.env.ref('collections_workbench.note_cat_no_answer')
        cls.cat_paid_full = cls.env.ref('collections_workbench.note_cat_paid_full')
        cls.cat_contacted = cls.env.ref('collections_workbench.note_cat_contacted')

    @classmethod
    def _invoice(cls, partner, amount, inv_date, post=True):
        move = cls.init_invoice('out_invoice', partner=partner, invoice_date=inv_date,
                                amounts=[amount], taxes=[], post=post)
        return move

    @classmethod
    def _pay(cls, invoice, amount, pay_date):
        return cls.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({'amount': amount, 'payment_date': pay_date})._create_payments()

    @classmethod
    def _unreconciled_payment(cls, partner, amount, pay_date):
        payment = cls.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': partner.id,
            'amount': amount,
            'date': pay_date,
        })
        payment.action_post()
        return payment

    def _snapshot(self, month=date(2026, 11, 1)):
        snap = self.env['collection.snapshot'].create({
            'period_type': 'before_month', 'month_date': month})
        snap._generate()
        return snap
