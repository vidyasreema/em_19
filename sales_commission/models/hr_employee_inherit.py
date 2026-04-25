from odoo import api, fields, models
from datetime import date
from dateutil.relativedelta import relativedelta


class HrEmployeeInherit(models.Model):
    _inherit = "hr.employee"

    is_sales_man = fields.Boolean(
        string="Is Sales Man",
    )

    @api.onchange('job_id')
    def _onchange_job_id_sales(self):
        """
        Auto-checks is_sales_man when job position is changed to 'Sales Man'.
        For existing employees, post_init_hook handles the backfill on upgrade.
        """
        self.is_sales_man = bool(self.job_id and self.job_id.name == "Sales Man")

    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id
    )

    # ── Per-Employee Commission Eligibility Rules ─────────────
    min_collection_rate = fields.Float(
        string='Minimum Collection Rate (%)',
        default=80.0,
        help='Salesperson must collect at least this % of invoiced amount to be eligible for commission'
    )
    target_achievement_required = fields.Boolean(
        string='Target Achievement Required',
        default=True,
        help='If enabled, salesperson must hit their sales target to get commission'
    )

    # ── Targets & Statements ──────────────────────────────────
    commission_target_ids = fields.One2many(
        'commission.target',
        'employee_id',
        string='Commission Targets'
    )

    commission_statement_ids = fields.One2many(
        'commission.statement',
        'employee_id',
        string='Commission Statements'
    )

    current_target_amount = fields.Monetary(
        string='Current Target Amount',
        currency_field='currency_id',
        compute='_compute_active_target',
    )
    current_commission_rate = fields.Float(
        string='Current Commission Rate (%)',
        compute='_compute_active_target',
    )

    @api.depends(
        'commission_target_ids',
        'commission_target_ids.target_amount',
        'commission_target_ids.commission_rate',
        'commission_target_ids.month'
    )
    def _compute_active_target(self):
        for rec in self:
            # Always fetch the most recent target by month using a proper search
            # so we always get the latest regardless of insertion order
            latest = self.env['commission.target'].search([
                ('employee_id', '=', rec.id),
            ], order='id desc', limit=1)
            if latest:
                rec.current_target_amount = latest.target_amount
                rec.current_commission_rate = latest.commission_rate
            else:
                rec.current_target_amount = 0.0
                rec.current_commission_rate = 0.0

    # ═════════════════════════════════════════════════════════
    # Dashboard: Get current year months (Jan → Dec of this year)
    # ═════════════════════════════════════════════════════════
    def action_refresh_statements(self):
        """Force recompute all unpaid statements for this employee.
        Called by the Refresh button on the dashboard so that changes
        to targets or commission rules are immediately reflected.
        """
        self.ensure_one()
        today = date.today()
        start_month = date(today.year, 1, 1)
        end_month = date(today.year, 12, 1)

        statements = self.env['commission.statement'].search([
            ('employee_id', '=', self.id),
            ('month', '>=', start_month),
            ('month', '<=', end_month),
            ('paid', '=', False),
            ('month_closed', '=', False),
        ])

        if statements:
            # Write latest target values directly — bypasses stored cache
            for st in statements:
                # Always use the latest target regardless of month
                target = self.env['commission.target'].search([
                    ('employee_id', '=', self.id),
                ], order='id desc', limit=1)
                vals = {
                    'cfg_min_collection_rate': self.min_collection_rate,
                    'cfg_target_required': self.target_achievement_required,
                }
                if target:
                    vals['target_id'] = target.id
                    vals['target_amount'] = target.target_amount
                    vals['commission_rate'] = target.commission_rate
                st.write(vals)
            # Recompute eligibility and status with fresh values
            statements._compute_metrics()
            statements._compute_eligibility()
            statements._compute_status()

    def action_get_commission_dashboard(self):
        self.ensure_one()
        today = date.today()

        start_month = date(today.year, 1, 1)
        end_month = date(today.year, 12, 1)

        # Force recompute all unpaid/unclosed statements for this employee
        # so Refresh always reflects latest targets, invoices, and rules.
        # Force recompute unpaid statements so latest target/rules are used
        statements_to_recompute = self.env['commission.statement'].search([
            ('employee_id', '=', self.id),
            ('paid', '=', False),
            ('month_closed', '=', False),
        ])
        if statements_to_recompute:
            # Write latest target values directly — bypasses stored cache
            for st in statements_to_recompute:
                # Always use the latest target regardless of month
                target = self.env['commission.target'].search([
                    ('employee_id', '=', self.id),
                ], order='id desc', limit=1)
                vals = {
                    'cfg_min_collection_rate': self.min_collection_rate,
                    'cfg_target_required': self.target_achievement_required,
                }
                if target:
                    vals['target_id'] = target.id
                    vals['target_amount'] = target.target_amount
                    vals['commission_rate'] = target.commission_rate
                st.write(vals)
            # Now recompute eligibility and status with fresh values
            statements_to_recompute._compute_metrics()
            statements_to_recompute._compute_eligibility()
            statements_to_recompute._compute_status()

        result = []
        current = start_month
        currency_symbol = self.env.company.currency_id.symbol or 'AED'

        while current <= end_month:
            statement = self.env['commission.statement'].search([
                ('employee_id', '=', self.id),
                ('month', '=', current),
            ], limit=1)

            if statement:
                target_pct = (
                    (statement.invoiced_net / statement.target_amount * 100)
                    if statement.target_amount > 0 else 0.0
                )
                min_rate = statement.cfg_min_collection_rate or 80.0
                required_collection = statement.invoiced_net * min_rate / 100
                amount_left = max(0, required_collection - statement.collected_net)

                display_commission = (
                    statement.paid_commission_amount
                    if statement.paid
                    else statement.payable_amount
                )

                result.append({
                    'month': current.strftime('%b %Y'),
                    'month_date': current.strftime('%Y-%m-%d'),
                    'statement_id': statement.id,
                    'has_statement': True,
                    'target_amount': statement.target_amount,
                    'invoiced_net': statement.invoiced_net,
                    'target_pct': round(target_pct, 1),
                    'collected_net': statement.collected_net,
                    'collection_pct': round(statement.collection_pct_of_sales, 1),
                    'amount_left': amount_left,
                    'payable_amount': display_commission,
                    'commission_base': statement.commission_base,
                    'status': statement.status,
                    'eligible': statement.eligible,
                    'paid': statement.paid,
                    'month_closed': statement.month_closed,
                    'journal_entry_state': statement.journal_entry_state or False,
                    'target_achieved': statement.target_achieved,
                    'currency_symbol': currency_symbol,
                })
            else:
                result.append({
                    'month': current.strftime('%b %Y'),
                    'month_date': current.strftime('%Y-%m-%d'),
                    'statement_id': False,
                    'has_statement': False,
                    'target_amount': 0,
                    'invoiced_net': 0,
                    'target_pct': 0,
                    'collected_net': 0,
                    'collection_pct': 0,
                    'amount_left': 0,
                    'payable_amount': 0,
                    'commission_base': 0,
                    'status': False,
                    'eligible': False,
                    'paid': False,
                    'month_closed': False,
                    'journal_entry_state': False,
                    'target_achieved': False,
                    'currency_symbol': currency_symbol,
                })

            current += relativedelta(months=1)

        return result

    # ═════════════════════════════════════════════════════════
    # Dashboard: Generate statement for a month
    # ═════════════════════════════════════════════════════════
    def action_generate_statement(self, month_date):
        self.ensure_one()
        from datetime import datetime
        from odoo.exceptions import UserError
        month = datetime.strptime(month_date, '%Y-%m-%d').date()

        # Block if already paid or closed
        existing = self.env['commission.statement'].search([
            ('employee_id', '=', self.id),
            ('month', '=', month),
        ], limit=1)

        if existing:
            if existing.paid or existing.month_closed:
                raise UserError(
                    f'Statement for {month.strftime("%B %Y")} is already '
                    f'paid and locked. It cannot be regenerated.\n\n'
                    f'Use "Reset to Draft" from the statement form if changes are needed.'
                )
            return existing.id

        # Validate: employee must have at least one commission target configured
        target = self.env['commission.target'].search([
            ('employee_id', '=', self.id),
        ], order='id desc', limit=1)

        if not target:
            raise UserError(
                f'Cannot generate statement for {month.strftime("%B %Y")}.\n\n'
                f'No commission target is configured for {self.name}.\n'
                f'Please add a target in the "Target History" tab first.'
            )

        statement = self.env['commission.statement'].create({
            'employee_id': self.id,
            'month': month,
            'cfg_min_collection_rate': self.min_collection_rate,
            'cfg_target_required': self.target_achievement_required,
        })
        return statement.id