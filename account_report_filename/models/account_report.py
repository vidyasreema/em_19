import logging
import re

from odoo import models

_logger = logging.getLogger(__name__)

# characters that break a download filename
INVALID_CHARS = r'[\\/:*?"<>|]'


class AccountReport(models.Model):
    _inherit = "account.report"

    def get_default_report_filename(self, options, extension):
        # Uncomment once to inspect the real structure, then remove:
        # _logger.warning("REPORT OPTIONS: %s", options)

        partner_ids = self._get_single_partner_from_options(options)
        if len(partner_ids) == 1:
            partner = self.env["res.partner"].browse(partner_ids[0]).exists()
            date = options.get("date") or {}
            date_from = self._format_report_date(date.get("date_from"))
            date_to = self._format_report_date(date.get("date_to"))

            if partner and date_from and date_to:
                name = "%s - %s to %s" % (partner.display_name, date_from, date_to)
                name = re.sub(INVALID_CHARS, "-", name).strip()
                return "%s.%s" % (name, extension)

        return super().get_default_report_filename(options, extension)

    def _get_single_partner_from_options(self, options):
        """Return the selected partner ids, whichever key the report uses."""
        for key in ("partner_ids", "res_partner_ids"):
            value = options.get(key)
            if value:
                return [v for v in value if isinstance(v, int)]

        # some reports carry it in the active context instead of options
        ctx_partner = self.env.context.get("active_id")
        if ctx_partner and self.env.context.get("active_model") == "res.partner":
            return [ctx_partner]

        return []

    def _format_report_date(self, value):
        """'2026-01-01' -> '01-01-2026'"""
        if not value:
            return ""
        value = str(value)[:10]
        parts = value.split("-")
        if len(parts) == 3:
            return "%s-%s-%s" % (parts[2], parts[1], parts[0])
        return value