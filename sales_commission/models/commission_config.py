from odoo import api, fields, models


class CommissionConfig(models.Model):
    _name = 'commission.config'
    _description = 'Commission Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade'
    )

    # ── Accounting (shared across all employees in the company) ──
    expense_account_id = fields.Many2one(
        'account.account',
        string='Commission Expense Account',
        help='Account to debit when commission is paid'
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        help='Journal used to post commission payments'
    )

    _sql_constraints = [
        (
            'unique_company',
            'UNIQUE(company_id)',
            'A configuration already exists for this company.'
        )
    ]

    @api.model
    def get_config(self):
        """Get config for current company. Create with defaults if not exists."""
        config = self.search([
            ('company_id', '=', self.env.company.id)
        ], limit=1)
        if not config:
            config = self.create({
                'company_id': self.env.company.id,
            })
        return config