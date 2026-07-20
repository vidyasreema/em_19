from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare
from odoo.tools.translate import _


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _payment_link_in_lines(self):
        """Statement lines of this session that belong to the Payment Link In journal."""
        self.ensure_one()
        journal = self.config_id.payment_link_in_journal_id
        if not journal:
            return self.env['account.bank.statement.line']
        return self.sudo().statement_line_ids.filtered(
            lambda l: l.journal_id == journal
        )

    def try_payment_link_in(self, amount, reason, partner_id=False):
        """Record incoming money on the configured non-cash journal."""
        self.ensure_one()

        if self.state != 'opened':
            raise UserError(_("The session is not open."))

        config = self.config_id
        if not config.payment_link_in_enabled:
            raise UserError(_("Payment Link In is not enabled for this point of sale."))

        journal = config.payment_link_in_journal_id
        if not journal:
            raise UserError(_("No Payment Link In journal configured for this point of sale."))

        amount = float(amount)
        if float_compare(amount, 0.0, precision_rounding=self.currency_id.rounding) <= 0:
            raise UserError(_("The amount must be greater than zero."))

        if not reason or not reason.strip():
            raise UserError(_("A note is required."))

        line = self.env['account.bank.statement.line'].create({
            'journal_id': journal.id,
            'amount': amount,
            'date': fields.Date.context_today(self),
            'payment_ref': '%s - %s' % (self.name, reason.strip()),
            'partner_id': partner_id or False,
            'pos_session_id': self.id,
        })
        # AC-04: hold the entry in draft until the session is closed.
        if line.move_id and line.move_id.state == 'posted':
            line.move_id.sudo().button_draft()
        return line.id

    def _post_payment_link_in_moves(self):
        """Post the Payment Link In entries held in draft during the session."""
        for session in self:
            moves = session._payment_link_in_lines().mapped('move_id').filtered(
                lambda m: m.state == 'draft'
            )
            if moves:
                moves.sudo()._post()

    def get_cash_in_out_list(self):
        """Exclude Payment Link In movements from the cash in/out list."""
        result = super().get_cash_in_out_list()
        pli_lines = self._payment_link_in_lines()
        if not pli_lines:
            return result
        pli_ids = set(pli_lines.ids)
        return [m for m in result if m.get('id') not in pli_ids]

    def get_closing_control_data(self):
        """Keep Payment Link In out of expected cash, and expose it as information."""
        data = super().get_closing_control_data()

        pli_lines = self._payment_link_in_lines()
        pli_total = sum(pli_lines.mapped('amount'))

        if data.get('default_cash_details') and pli_total:
            data['default_cash_details']['amount'] -= pli_total

        data['payment_link_in_details'] = {
            'name': self.config_id.payment_link_in_journal_id.name or _("Payment Link In"),
            'amount': pli_total,
            'number': len(pli_lines),
        }
        return data

    def _validate_session(self, *args, **kwargs):
        res = super()._validate_session(*args, **kwargs)
        self._post_payment_link_in_moves()
        return res