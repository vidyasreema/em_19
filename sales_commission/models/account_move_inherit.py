from odoo import api, fields, models
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)


class AccountMoveCommission(models.Model):
    _inherit = 'account.move'

    commission_salesman_id = fields.Many2one(
        'hr.employee',
        string='Commission Salesman (Snapshot)',
        index=True,
        readonly=True,
        help='Salesman captured at invoice creation. '
             'Does NOT change if the contact is reassigned later.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for move in records:
            if (
                    move.move_type == 'out_invoice'
                    and not move.commission_salesman_id
                    and move.partner_id
                    and move.partner_id.sales_man
            ):
                move.commission_salesman_id = move.partner_id.sales_man
        return records

    @api.onchange('partner_id')
    def _onchange_partner_commission_salesman(self):
        if (
                self.move_type == 'out_invoice'
                and self.state == 'draft'
                and self.partner_id
                and self.partner_id.sales_man
        ):
            self.commission_salesman_id = self.partner_id.sales_man

    @api.model
    def action_backfill_commission_salesman(self):

        invoices = self.env['account.move'].search([
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('commission_salesman_id', '=', False),
            ('partner_id', '!=', False),
        ])

        total = len(invoices)
        updated = 0
        skipped = 0

        for idx, inv in enumerate(invoices, start=1):
            if inv.partner_id.sales_man:
                inv.sudo().write({
                    'commission_salesman_id': inv.partner_id.sales_man.id
                })
                updated += 1
            else:
                skipped += 1

            # ✅ Log count every 100 records
            if idx % 100 == 0:
                self.env.cr.commit()  # commit so progress is saved live
                _logger.info(
                    'Backfill Progress: %d / %d | Updated: %d | Skipped: %d',
                    idx, total, updated, skipped
                )

        _logger.info(
            'Backfill DONE: Total: %d | Updated: %d | Skipped: %d',
            total, updated, skipped
        )

        raise UserError(
            f'Backfill Complete!\n\n'
            f'Total   : {total}\n'
            f'Updated : {updated}\n'
            f'Skipped : {skipped}'
        )