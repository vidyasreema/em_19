from odoo import _, api, models
from odoo.tools import formatLang


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def get_pos_credit_status(self, partner_id):
        """Single source of truth for the POS credit block.

        Called by the POS front end (to grey out the button) and by
        pos.order on sync (to actually enforce it). Never duplicate
        this rule anywhere else.
        """
        partner = self.browse(partner_id).exists()
        if not partner:
            return {"blocked": False, "message": ""}
        limit = partner.credit_limit
        balance = partner.credit

        # limit of 0 means "not configured" -> no block
        blocked = bool(limit) and balance > limit

        currency = partner.company_id.currency_id or self.env.company.currency_id
        message = ""
        if blocked:
            message = _(
                "%(name)s has exceeded the credit limit.\n\n"
                "Outstanding: %(balance)s\n"
                "Credit limit: %(limit)s\n\n"
                "Please take payment by cash, card or bank transfer.",
                name=partner.display_name,
                balance=formatLang(self.env, balance, currency_obj=currency),
                limit=formatLang(self.env, limit, currency_obj=currency),
            )

        return {
            "blocked": blocked,
            "balance": balance,
            "limit": limit,
            "message": message,
            "partner_name": partner.display_name,
        }