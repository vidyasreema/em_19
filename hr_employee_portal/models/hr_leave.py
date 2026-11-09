from odoo import models
from odoo.exceptions import UserError

from .hr_employee import OPEN_LEAVE_STATES


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def _ep_portal_decide(self, decision, user):
        """Approve or refuse a request from the HR dashboard of the portal, for
        `user` (an HR admin of the portal, without rights on HR models: called
        with sudo). The decision is noted in the request's chatter as theirs."""
        self.ensure_one()
        if self.state not in OPEN_LEAVE_STATES:
            raise UserError(self.env._("This request was already approved or refused."))
        if self.employee_id.user_id == user:
            raise UserError(self.env._("You cannot approve or refuse your own leave."))
        if decision == 'approve':
            # Two rounds for types that need two approvals.
            for _round in range(2):
                if self.state in OPEN_LEAVE_STATES:
                    self.action_approve()
            body = self.env._("Approved by %s from the employee portal.", user.name)
        elif decision == 'refuse':
            self.action_refuse()
            body = self.env._("Refused by %s from the employee portal.", user.name)
        else:
            raise UserError(self.env._("Unknown decision."))
        self.message_post(body=body, author_id=user.partner_id.id, subtype_xmlid='mail.mt_note')
