import contextlib
import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _action_reset_password(self, signup_type="reset"):
        """Reset password of website customers: The Cut email, from no-reply@
        (Odoo's standard one is not a template and signs with "Public user")."""
        context = self.env.context
        template = self.env.ref('website_brand_emails.mail_template_reset_password', raise_if_not_found=False)
        if (signup_type != 'reset' or not template or context.get('create_user')
                or context.get('install_mode') or context.get('import_file')):
            return super()._action_reset_password(signup_type=signup_type)
        Website = self.env['website'].sudo()
        customers = self.filtered(lambda user: Website._brand_website_for(user))
        others = self - customers
        result = super(ResUsers, others)._action_reset_password(signup_type=signup_type) if others else None
        if not customers:
            return result
        if customers.filtered(lambda user: not user.active):
            raise UserError(_("You cannot perform this action on an archived user."))
        customers.mapped('partner_id').signup_prepare(signup_type=signup_type)
        for user in customers:
            if not user.email:
                raise UserError(_("Cannot send email: user %s has no email address.", user.name))
            # Like the standard email: the email record is not kept
            with contextlib.closing(self.env.cr.savepoint()):
                template.send_mail(user.id, force_send=True, raise_exception=True, email_values={
                    'email_to': user.email,
                    'email_cc': False,
                    'auto_delete': True,
                    'message_type': 'user_notification',
                    'recipient_ids': [],
                    'partner_ids': [],
                    'scheduled_date': False,
                })
            _logger.info("Password reset email (The Cut) sent for user <%s> to <%s>", user.login, user.email)
        return result or {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Notification',
                'message': _('A reset password link was sent by email'),
                'sticky': False,
            },
        }
