from markupsafe import Markup

from odoo import Command, _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _signup_guest_records(self, email):
        """Customer records of an email that have no account (guest orders),
        most recent first: the latest order, else the latest created.
        :param str email: normalized email"""
        if not email:
            return self.browse()
        partners = self.sudo().search([('email_normalized', '=', email), ('parent_id', '=', False)])
        partners = partners.filtered(lambda p: not p.with_context(active_test=False).user_ids)
        if not partners:
            return partners
        last_order = dict(self.env['sale.order'].sudo()._read_group(
            [('partner_id', 'in', partners.ids)], ['partner_id'], ['date_order:max']))
        return partners.sorted(lambda p: (last_order.get(p) or p.create_date, p.id), reverse=True)

    def _signup_flag_duplicates(self, kept, order=None):
        """Other records of the email of a new account: tagged for the daily
        check, where they are merged into the account's record (Annex 3A 4.2).
        :param order: guest order placed with the email of an account that did
            not prove it (not added to that account automatically)"""
        tag = self.env.ref('website_signup_verification.partner_tag_duplicate_email', raise_if_not_found=False)
        if order:
            body = Markup(_("Guest order %(order)s with the email of the account %(account)s, which did not "
                            "confirm its email: not added to it automatically. Check it and merge it into "
                            "that customer (Action > Merge).")) % {
                'order': order._get_html_link(), 'account': kept._get_html_link()}
        else:
            body = Markup(_("Same email as %(account)s, who created an account on %(date)s. "
                            "Check it and merge it into that customer (Action > Merge).")) % {
                'account': kept._get_html_link(), 'date': fields.Date.context_today(self)}
        for partner in self.sudo():
            if tag:
                partner.category_id = [Command.link(tag.id)]
            partner.message_post(body=body, subtype_xmlid='mail.mt_note')
