from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    pli_session_id = fields.Many2one(
        'pos.session',
        string="Payment Link In Session",
        index=True,
        copy=False,
        help="Session in which this Payment Link In movement was recorded. "
             "Deliberately separate from pos_session_id so the amount is never "
             "treated as cash.",
    )