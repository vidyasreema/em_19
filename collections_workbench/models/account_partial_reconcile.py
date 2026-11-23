import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        # A payment matched with an invoice: partial payment / full payment
        # rules apply at once instead of waiting for the daily job (BR-13, BR-25).
        partners = (partials.debit_move_id | partials.credit_move_id).partner_id.filtered(
            'collection_pipeline_id')
        for partner in partners:
            try:
                with self.env.cr.savepoint():
                    partner._collection_recompute_status()
            except Exception:
                _logger.exception("Collections: status update after reconciliation failed for %s", partner.id)
        return partials
