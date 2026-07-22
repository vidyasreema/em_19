from odoo import models,fields, _
from odoo.exceptions import UserError
from datetime import timedelta

POS_RESET_LOCK_HOURS = 30


class AccountMove(models.Model):
    _inherit = 'account.move'

    def unlink(self):
        if not self.env.su and not self.env.user.has_group('em_custom.group_journal_entry_delete'):
            protected = self.filtered(
                lambda m: m.posted_before or (m.name and m.name != '/')
            )
            if protected:
                raise UserError(_(
                    "You don't have permission to delete accounting entries. "
                    "Contact your administrator if you need this access."
                ))
        return super().unlink()

    def get_extra_print_items(self):
        # POS, cash and bank entries have no partner. Core passes the empty
        # partner recordset to _get_ubl_cii_edi_format(), which calls
        # ensure_one() and raises "Expected singleton: res.partner()".
        if not self.commercial_partner_id:
            return []
        return super().get_extra_print_items()

    def button_draft(self):
        if not self.env.su and not self.env.user.has_group('em_custom.group_pos_invoice_reset_draft'):
            deadline = fields.Datetime.now() - timedelta(hours=POS_RESET_LOCK_HOURS)
            locked = self.filtered(
                lambda m: m.pos_order_ids and m.create_date and m.create_date <= deadline
            )
            if locked:
                raise UserError(_(
                    "POS invoices can only be reset to draft within %s hours of creation. "
                    "Please contact the main account.",
                    POS_RESET_LOCK_HOURS,
                ))
        return super().button_draft()