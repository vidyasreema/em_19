from odoo import api, fields, models
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta


class CommissionStatement(models.Model):
    _name = 'commission.statement'
    _description = 'Monthly Commission Statement'
    _order = 'month desc'

    # ── Core ──────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee',
        string='Salesperson',
        required=True,
        ondelete='cascade'
    )
    month = fields.Date(string='Month', required=True)
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company
    )

    # ── Target ────────────────────────────────────────────────
    target_id = fields.Many2one(
        'commission.target',
        string='Target',
        compute='_compute_target_id',
        store=True
    )
    target_amount = fields.Monetary(
        string='Target Amount',
        currency_field='currency_id',
        compute='_compute_target_id',
        store=True
    )
    commission_rate = fields.Float(
        string='Commission Rate (%)',
        compute='_compute_target_id',
        store=True
    )

    # ── Invoice Counts ────────────────────────────────────────
    invoice_count = fields.Integer(
        string='Total Invoices',
        compute='_compute_metrics',
        store=True
    )
    invoice_fully_paid_count = fields.Integer(
        string='Fully Paid',
        compute='_compute_metrics',
        store=True
    )
    invoice_partial_paid_count = fields.Integer(
        string='Partially Paid',
        compute='_compute_metrics',
        store=True
    )
    invoice_cancelled_count = fields.Integer(
        string='Cancelled',
        compute='_compute_metrics',
        store=True
    )
    invoice_refunded_count = fields.Integer(
        string='Refunded',
        compute='_compute_metrics',
        store=True
    )

    # ── Sales Metrics ─────────────────────────────────────────
    invoiced_net = fields.Monetary(
        string='Total Sales (Net)',
        compute='_compute_metrics',
        store=True,
        currency_field='currency_id'
    )
    collected_net = fields.Monetary(
        string='Collected (Fully Paid)',
        compute='_compute_metrics',
        store=True,
        currency_field='currency_id'
    )
    outstanding = fields.Monetary(
        string='Outstanding',
        compute='_compute_metrics',
        store=True,
        currency_field='currency_id'
    )
    collection_pct_of_sales = fields.Float(
        string='Collection % of Sales',
        compute='_compute_metrics',
        store=True,
        help='Collected / Total Sales x 100'
    )

    # ── Config Snapshot ───────────────────────────────────────
    cfg_min_collection_rate = fields.Float(
        string='Min Collection Rate Used',
        store=True
    )
    cfg_target_required = fields.Boolean(
        string='Target Required',
        store=True
    )

    # ── Eligibility ───────────────────────────────────────────
    target_achieved = fields.Boolean(
        string='Target Achieved',
        compute='_compute_eligibility',
        store=True
    )
    eligible = fields.Boolean(
        string='Eligible for Payout',
        compute='_compute_eligibility',
        store=True
    )
    commission_base = fields.Monetary(
        string='Commission Base (Step 1)',
        compute='_compute_eligibility',
        store=True,
        currency_field='currency_id',
        help='Step 1: Collected Amount x Commission Rate%'
    )
    payable_amount = fields.Monetary(
        string='Payable Commission (Step 2)',
        compute='_compute_eligibility',
        store=True,
        currency_field='currency_id',
        help='Step 2: Commission Base x Commission Rate%'
    )

    # ── Payment ───────────────────────────────────────────────
    paid = fields.Boolean(string='Paid', default=False)
    paid_date = fields.Date(string='Payment Date')
    payment_ref = fields.Char(string='Payment Reference')

    paid_commission_amount = fields.Monetary(
        string='Commission Paid',
        currency_field='currency_id',
        store=True,
        readonly=True,
        help='Snapshot of the commission amount at the time of payment.'
    )

    # ── Payment Locks ─────────────────────────────────────────
    original_paid_month = fields.Date(
        string='Original Paid Month',
        readonly=True,
        store=True,
        help='Month locked at time of first payment. Cannot be changed.'
    )
    original_paid_employee_id = fields.Many2one(
        'hr.employee',
        string='Original Paid Employee',
        readonly=True,
        store=True,
        ondelete='restrict',
        help='Employee locked at time of first payment. Cannot be changed.'
    )

    month_closed = fields.Boolean(string='Month Closed', default=False)
    journal_entry_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True
    )

    journal_entry_state = fields.Selection(
        related='journal_entry_id.state',
        string='Journal Entry State',
        store=True,
        readonly=True
    )

    # ── Status ────────────────────────────────────────────────
    status = fields.Selection([
        ('not_achieved',        'Not Achieved'),
        ('pending_collections', 'Pending Collections'),
        ('ready_to_pay',        'Ready to Pay'),
        ('paid',                'Paid'),
        ('month_closed',        'Month Closed'),
    ], string='Status', compute='_compute_status', store=True)

    _sql_constraints = [
        (
            'unique_employee_month',
            'UNIQUE(employee_id, month)',
            'A statement already exists for this employee in this month.'
        )
    ]

    @api.constrains('month')
    def _check_month_not_changed_after_payment(self):
        for rec in self:
            if (
                    rec.original_paid_month
                    and rec.month != rec.original_paid_month
            ):
                raise ValidationError(
                    f'Cannot change the month of a statement that was '
                    f'previously paid.\n\n'
                    f'This statement was originally created for '
                    f'{rec.original_paid_month.strftime("%B %Y")}.\n\n'
                    f'To use a different month:\n'
                    f'  1. Use "Reset to Draft"\n'
                    f'  2. Delete this statement\n'
                    f'  3. Create a new statement for the correct month.'
                )

    @api.constrains('employee_id')
    def _check_employee_not_changed_after_payment(self):
        for rec in self:
            if (
                    rec.original_paid_employee_id
                    and rec.employee_id != rec.original_paid_employee_id
            ):
                raise ValidationError(
                    f'Cannot change the salesperson of a statement that '
                    f'was previously paid.\n\n'
                    f'This statement was originally created for '
                    f'{rec.original_paid_employee_id.name}.\n\n'
                    f'To use a different salesperson:\n'
                    f'  1. Use "Reset to Draft"\n'
                    f'  2. Delete this statement\n'
                    f'  3. Create a new statement for the correct '
                    f'salesperson.'
                )

    # ═════════════════════════════════════════════════════════
    # STEP 1: Find applicable target for this month
    # ═════════════════════════════════════════════════════════
    @api.depends('employee_id', 'month', 'employee_id.commission_target_ids',
                 'employee_id.commission_target_ids.target_amount',
                 'employee_id.commission_target_ids.commission_rate',
                 'employee_id.commission_target_ids.month')
    def _compute_target_id(self):
        for rec in self:

            # ── LOCK: skip recompute for paid or closed statements ──
            if rec.paid or rec.month_closed:
                continue

            if not rec.employee_id or not rec.month:
                rec.target_id = False
                rec.target_amount = 0.0
                rec.commission_rate = 0.0
                continue

            target = self.env['commission.target'].search([
                ('employee_id', '=', rec.employee_id.id),
            ], order='id desc', limit=1)

            rec.target_id = target
            rec.target_amount = target.target_amount if target else 0.0
            rec.commission_rate = target.commission_rate if target else 0.0

    # ═════════════════════════════════════════════════════════
    # STEP 2: Calculate metrics from invoices
    # ═════════════════════════════════════════════════════════
    @api.depends('employee_id', 'month',
                 'employee_id.min_collection_rate',
                 'employee_id.target_achievement_required')
    def _compute_metrics(self):
        for rec in self:
            if not rec.employee_id or not rec.month:
                rec._reset_metrics()
                continue

            date_from = rec.month
            date_to = rec.month + relativedelta(months=1, days=-1)

            invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', date_from),
                ('invoice_date', '<=', date_to),
                ('partner_id.sales_man', '=', rec.employee_id.id),
            ])

            credit_notes = self.env['account.move'].search([
                ('move_type', '=', 'out_refund'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', date_from),
                ('invoice_date', '<=', date_to),
                ('partner_id.sales_man', '=', rec.employee_id.id),
            ])

            cancelled = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'cancel'),
                ('invoice_date', '>=', date_from),
                ('invoice_date', '<=', date_to),
                ('partner_id.sales_man', '=', rec.employee_id.id),
            ])

            rec.invoice_count = len(invoices)
            rec.invoice_fully_paid_count = len(
                invoices.filtered(lambda i: i.payment_state == 'paid'))
            rec.invoice_partial_paid_count = len(
                invoices.filtered(lambda i: i.payment_state == 'partial'))
            rec.invoice_cancelled_count = len(cancelled)
            rec.invoice_refunded_count = len(credit_notes)

            total_sales = 0.0
            collected_sales = 0.0

            for inv in invoices:
                inv_sales = sum(
                    line.quantity * line.price_unit *
                    (1 - (line.discount or 0.0) / 100)
                    for line in inv.invoice_line_ids.filtered(
                        lambda l: l.display_type == 'product')
                )
                total_sales += inv_sales
                if inv.payment_state == 'paid':
                    collected_sales += inv_sales

            for cn in credit_notes:
                refund_amount = sum(
                    line.quantity * line.price_unit *
                    (1 - (line.discount or 0.0) / 100)
                    for line in cn.invoice_line_ids.filtered(
                        lambda l: l.display_type == 'product')
                )
                total_sales -= refund_amount

            rec.invoiced_net = total_sales
            rec.collected_net = collected_sales
            rec.outstanding = total_sales - collected_sales
            rec.collection_pct_of_sales = (
                (collected_sales / total_sales * 100)
                if total_sales > 0 else 0.0
            )

            rec.cfg_min_collection_rate = rec.employee_id.min_collection_rate or 80.0
            rec.cfg_target_required = rec.employee_id.target_achievement_required

    def _reset_metrics(self):
        for f in [
            'invoice_count', 'invoice_fully_paid_count',
            'invoice_partial_paid_count', 'invoice_cancelled_count',
            'invoice_refunded_count', 'invoiced_net', 'collected_net',
            'outstanding', 'collection_pct_of_sales',
        ]:
            self[f] = 0

    # ═════════════════════════════════════════════════════════
    # STEP 3: Eligibility + Commission
    # ═════════════════════════════════════════════════════════
    @api.depends(
        'invoiced_net', 'collected_net', 'target_amount',
        'collection_pct_of_sales', 'commission_rate',
        'paid', 'month_closed',
        'cfg_min_collection_rate', 'cfg_target_required'
    )
    def _compute_eligibility(self):
        for rec in self:
            if rec.cfg_target_required:
                rec.target_achieved = (
                        rec.target_amount > 0
                        and rec.invoiced_net >= rec.target_amount
                )
            else:
                rec.target_achieved = True

            min_rate = rec.cfg_min_collection_rate or 80.0
            collection_ok = rec.collection_pct_of_sales >= min_rate

            rec.eligible = (
                    rec.target_achieved
                    and collection_ok
                    and not rec.paid
                    and not rec.month_closed
            )

            if rec.commission_rate > 0 and rec.collected_net > 0:
                step1 = rec.collected_net * (rec.commission_rate / 100)
                step2 = step1 * (rec.commission_rate / 100)
                rec.commission_base = step1
                rec.payable_amount = step2 if rec.eligible else 0.0
            else:
                rec.commission_base = 0.0
                rec.payable_amount = 0.0

    # ═════════════════════════════════════════════════════════
    # STEP 4: Status
    # ═════════════════════════════════════════════════════════
    @api.depends(
        'target_achieved', 'eligible', 'paid',
        'month_closed', 'journal_entry_id', 'journal_entry_state'
    )
    def _compute_status(self):
        for rec in self:
            if rec.month_closed:
                rec.status = 'month_closed'
            elif rec.paid and rec.journal_entry_state == 'posted':
                # ── Auto-close: journal posted → flag month as closed ──
                # Using sudo write to avoid compute side-effect issues
                rec.sudo().write({'month_closed': True})
                rec.status = 'month_closed'
            elif rec.paid and rec.journal_entry_id:
                rec.status = 'paid'
            elif rec.eligible:
                rec.status = 'ready_to_pay'
            elif rec.target_achieved:
                rec.status = 'pending_collections'
            else:
                rec.status = 'not_achieved'

    # ═════════════════════════════════════════════════════════
    # STEP 5: Reset to Draft
    # ═════════════════════════════════════════════════════════
    def action_reset_to_draft(self):
        self.ensure_one()

        # ── Allow reset from both paid (journal draft) and month_closed (journal posted) ──
        if not self.paid and not self.month_closed:
            raise ValidationError('Statement is not paid yet.')

        if self.journal_entry_id:
            if self.journal_entry_id.state == 'posted':
                # Reset posted journal back to draft so accountant can fix it
                self.journal_entry_id.button_draft()
            elif self.journal_entry_id.state == 'cancel':
                raise ValidationError(
                    'Journal entry is already cancelled. '
                    'Please handle it manually in accounting.')

        self.write({
            'paid': False,
            'paid_date': False,
            'payment_ref': False,
            'month_closed': False,
            'journal_entry_id': False,
            'paid_commission_amount': 0.0,
        })

    # ═════════════════════════════════════════════════════════
    # STEP 6: Block deletion of paid statements
    # ═════════════════════════════════════════════════════════
    def unlink(self):
        for rec in self:
            if rec.paid or rec.month_closed:
                raise ValidationError(
                    f'Cannot delete statement for '
                    f'{rec.employee_id.name} '
                    f'({rec.month.strftime("%B %Y")}) because '
                    f'commission has already been paid.\n\n'
                    f'Deleting a paid statement will cause '
                    f'accounting inconsistencies.\n'
                    f'Please use "Reset to Draft" button instead.'
                )
        return super().unlink()

    # ═════════════════════════════════════════════════════════
    # STEP 7: Pay Commission + Create Journal Entry (DRAFT)
    # ═════════════════════════════════════════════════════════
    def action_pay_commission(self):
        self.ensure_one()
        if not self.eligible:
            raise ValidationError(
                'This statement is not eligible for payout.')

        config = self.env['commission.config'].get_config()

        if not config.expense_account_id:
            raise ValidationError(
                'Please set a Commission Expense Account '
                'in Commission Settings configuration.')

        if not config.journal_id:
            raise ValidationError(
                'Please set a Payment Journal '
                'in Commission Settings configuration.')

        if not config.journal_id.default_account_id:
            raise ValidationError(
                'The selected journal has no default account set.')

        amount_to_pay = self.payable_amount

        move_vals = {
            'move_type': 'entry',
            'journal_id': config.journal_id.id,
            'date': fields.Date.today(),
            'ref': (
                f'Commission - {self.employee_id.name} - '
                f'{self.month.strftime("%B %Y")}'
            ),
            'line_ids': [
                (0, 0, {
                    'account_id': config.expense_account_id.id,
                    'name': f'Commission - {self.employee_id.name}',
                    'debit': amount_to_pay,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': config.journal_id.default_account_id.id,
                    'name': f'Commission - {self.employee_id.name}',
                    'debit': 0.0,
                    'credit': amount_to_pay,
                }),
            ],
        }
        journal_entry = self.env['account.move'].create(move_vals)

        self.write({
            'paid': True,
            'paid_date': fields.Date.today(),
            'payment_ref': journal_entry.name,
            'journal_entry_id': journal_entry.id,
            'paid_commission_amount': amount_to_pay,
            'original_paid_month': self.month,
            'original_paid_employee_id': self.employee_id.id,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': journal_entry.id,
            'view_mode': 'form',
            'target': 'current',
        }