from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import UserError

UNRECONCILE_LOCK_HOURS = 24


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    def unlink(self):
        if not self.env.su and not self.env.user.has_group('em_custom.group_unreconcile_locked'):
            deadline = fields.Datetime.now() - timedelta(hours=UNRECONCILE_LOCK_HOURS)
            locked = self.filtered(lambda p: p.create_date and p.create_date <= deadline)
            if locked:
                raise UserError(_(
                    "Payments reconciled more than %s hours ago can no longer be "
                    "unreconciled. Please contact the main account.",
                    UNRECONCILE_LOCK_HOURS,
                ))
        return super().unlink()