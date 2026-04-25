# -*- coding: utf-8 -*-
from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    ACTIVITY_SUMMARY = 'Unreconciled Customer Payment'
    ACTIVITY_NOTE = (
        "<p><strong>Unreconciled customer payment detected.</strong></p>"
        "<p>A payment or credit exists under this customer but is not matched with any invoice.</p>"
        "<p>Please review the customer ledger and reconcile the payment with the correct invoice.</p>"
        "<p>This is required to maintain accurate Accounts Receivable and avoid errors "
        "in the Aged Receivable report.</p>"
    )

    @api.model
    def _check_unreconciled_payments(self):
        _logger.info("=== Starting Unreconciled Customer Payment Check ===")
        self._close_resolved_activities()
        self._create_unreconciled_activities()
        _logger.info("=== Unreconciled Customer Payment Check Completed ===")

    @api.model
    def _create_unreconciled_activities(self):
        unreconciled_lines = self.search([
            ('account_id.account_type', '=', 'asset_receivable'),
            ('reconciled', '=', False),
            ('amount_residual', '!=', 0),
            ('move_id.state', '=', 'posted'),
            ('credit', '>', 0),
            ('partner_id', '!=', False),
        ])

        if not unreconciled_lines:
            _logger.info("No unreconciled customer payments found.")
            return

        partners = unreconciled_lines.mapped('partner_id')
        _logger.info("Found %d partner(s) with unreconciled payments.", len(partners))

        for partner in partners:
            if self._has_existing_activity(partner):
                _logger.info("Skipping partner '%s' — activity already exists.", partner.name)
                continue

            partner_lines = unreconciled_lines.filtered(lambda l: l.partner_id == partner)
            _logger.info(
                "Creating activity for partner '%s' — %d unreconciled line(s).",
                partner.name, len(partner_lines),
            )

            # Same pattern as _get_followup_responsible() in follow-up cron
            partner.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=fields.Date.today(),
                summary=self.ACTIVITY_SUMMARY,
                note=self.ACTIVITY_NOTE,
                user_id=self._get_unreconciled_responsible().id,
            )

    @api.model
    @api.model
    def _get_unreconciled_responsible(self):
        """
        Returns the responsible user for unreconciled payment activities.
        Searches by user name 'Account'. Falls back to current user if not found.
        """
        user = self.env['res.users'].search([
            ('name', '=', 'Account'),
            ('active', '=', True),
        ], limit=1)
        if not user:
            _logger.warning("User 'Account' not found. Falling back to current user.")
        return user or self.env.user

    @api.model
    def _close_resolved_activities(self):
        open_activities = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'),
            ('summary', '=', self.ACTIVITY_SUMMARY),
            ('activity_type_id', '=', self.env.ref('mail.mail_activity_data_todo').id),
        ])

        if not open_activities:
            return

        for activity in open_activities:
            partner = self.env['res.partner'].browse(activity.res_id)
            still_unreconciled = self.search_count([
                ('partner_id', '=', partner.id),
                ('account_id.account_type', '=', 'asset_receivable'),
                ('reconciled', '=', False),
                ('amount_residual', '!=', 0),
                ('move_id.state', '=', 'posted'),
                ('credit', '>', 0),
            ])
            if not still_unreconciled:
                _logger.info("Partner '%s' reconciled — auto-closing activity.", partner.name)
                activity.action_feedback(
                    feedback="Payment has been reconciled. Activity auto-closed by system."
                )

    @api.model
    def _has_existing_activity(self, partner):
        return bool(self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', partner.id),
            ('summary', '=', self.ACTIVITY_SUMMARY),
            ('activity_type_id', '=', self.env.ref('mail.mail_activity_data_todo').id),
        ], limit=1))