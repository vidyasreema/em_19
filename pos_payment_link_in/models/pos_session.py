from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare
from odoo.tools.translate import _


class PosSession(models.Model):
    _inherit = 'pos.session'

    payment_link_in_line_ids = fields.One2many(
        'account.bank.statement.line',
        'pli_session_id',
        string="Payment Link In Movements",
        readonly=True,
    )

    payment_link_in_count = fields.Integer(
        compute='_compute_payment_link_in_count',
    )

    def _compute_payment_link_in_count(self):
        for session in self:
            session.payment_link_in_count = len(session.payment_link_in_line_ids)

    def action_view_payment_link_in(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Payment Link In"),
            'res_model': 'account.bank.statement.line',
            'view_mode': 'list,form',
            'domain': [('pli_session_id', '=', self.id)],
        }

    def try_payment_link_in(self, amount, reason, partner_id=False):
        """Record incoming money on the configured non-cash journal.

        The line is linked through pli_session_id, never pos_session_id, so it
        can never affect the expected cash balance or the cash difference.
        """
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
            'payment_ref': '%s-in-%s' % (self.name, reason.strip()),
            'partner_id': partner_id or False,
            'pli_session_id': self.id,
        })
        # AC-04: hold in draft until the session is closed.
        if line.move_id and line.move_id.state == 'posted':
            line.move_id.sudo().button_draft()
        return line.id

    def _post_payment_link_in_moves(self):
        for session in self:
            moves = session.payment_link_in_line_ids.mapped('move_id').filtered(
                lambda m: m.state == 'draft'
            )
            if moves:
                moves.sudo()._post()

    def get_closing_control_data(self):
        """Expose the Payment Link In total as information only."""
        data = super().get_closing_control_data()
        lines = self.sudo().payment_link_in_line_ids
        data['payment_link_in_details'] = {
            'name': self.config_id.payment_link_in_journal_id.name or _("Payment Link In"),
            'amount': sum(lines.mapped('amount')),
            'number': len(lines),
        }
        return data

    def _validate_session(self, *args, **kwargs):
        res = super()._validate_session(*args, **kwargs)
        self._post_payment_link_in_moves()
        return res