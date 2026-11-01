from markupsafe import Markup

from odoo import _, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    order_source_id = fields.Many2one(
        'website.order.source',
        string='Heard About Us',
        tracking=True,
        copy=False,
        index='btree_not_null',
        help='How the customer heard about us, answered on the confirmation page of the website.',
    )

    def _order_source_answer(self, source):
        """The customer's answer (website): saved on the order and written in
        its history by the customer. Answered once; read-only on the order."""
        self.ensure_one()
        order = self.sudo()
        if order.order_source_id:
            return
        order.with_context(mail_notrack=True).order_source_id = source
        order.message_post(
            body=Markup(_("How did you hear about us? <b>%(source)s</b> (answered on the website)")) % {
                'source': source.name},
            author_id=order.partner_id.id,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
