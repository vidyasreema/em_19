from odoo import _, models
from odoo.tools.i18n import format_list


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _my_account_profile(self):
        """How complete the profile is, for the profile card of My Account.
        :return: {'percent': 0-100, 'missing': 'your mobile number and a delivery address'}"""
        self.ensure_one()
        partner = self.sudo()
        has_address = bool(partner.street) or any(
            child.type == 'delivery' and child.street for child in partner.child_ids)
        steps = [
            (partner.name, _("your name")),
            (partner.email, _("your email")),
            (partner.phone, _("your mobile number")),
            (has_address, _("a delivery address")),
        ]
        missing = [label for done, label in steps if not done]
        return {
            'percent': round(100 * (len(steps) - len(missing)) / len(steps)),
            'missing': format_list(self.env, missing) if missing else '',
            'initial': (partner.name or partner.email or '?').strip()[:1].upper(),
        }
