import json
import datetime
from odoo import models, api


class CustomerPerformanceReport(models.AbstractModel):
    """
    Abstract model for the Customer Performance Analysis PDF report.

    This model bridges the QWeb template with the data layer.
    It injects `json` and `datetime` modules into the template context
    because QWeb cannot import Python modules directly.

    Field names (x_studio_*) are Studio-generated fields that already
    exist on res.partner — this report reads them as-is, no recomputation.
    """
    _name = 'report.custom_contact_report.customer_performance_template'
    _description = 'Customer Performance Analysis Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        # Support both single and multi-record print from list view
        partners = self.env['res.partner'].browse(docids)

        # original_customer_ids is set by the wizard/action when printing
        # multiple customers merged into one summary partner record
        original_ids = (data or {}).get('original_customer_ids', docids)

        return {
            # Standard Odoo report context keys
            'doc_ids': docids,
            'doc_model': 'res.partner',
            'docs': partners,

            # Python built-ins needed by the template
            'json': json,
            'datetime': datetime,

            # Pass original ids so the template can detect group vs single
            'original_customer_ids': original_ids,

            # Expose env for browsing related records in the template
            'env': self.env,
        }
