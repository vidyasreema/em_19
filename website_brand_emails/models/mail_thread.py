from odoo import models

from .mail_template import BRAND_LAYOUT


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def message_post_with_source(self, source_ref, **kwargs):
        """Order confirmation and board emails: The Cut version for website orders."""
        template, _view = self._get_source_from_ref(source_ref)
        if template and len(self) == 1:
            brand, website = template._brand_version(self.id)
            if website:
                kwargs['email_layout_xmlid'] = BRAND_LAYOUT
                return super().message_post_with_source(brand, **kwargs)
        return super().message_post_with_source(source_ref, **kwargs)
