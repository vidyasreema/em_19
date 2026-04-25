from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CommissionTarget(models.Model):
    _name = 'commission.target'
    _description = 'Sales Commission Target'
    _order = 'month desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Salesperson',
        required=True,
        ondelete='cascade'
    )
    month = fields.Date(
        string='Month',
        required=True,
        help='Stored as first day of month e.g. 2026-01-01'
    )
    target_amount = fields.Monetary(
        string='Target Amount',
        currency_field='currency_id',
        required=True
    )
    commission_rate = fields.Float(
        string='Commission Rate (%)',
        default=10.0,
        required=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id
    )
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        (
            'unique_employee_month',
            'UNIQUE(employee_id, month)',
            'A target already exists for this employee in this month.'
        )
    ]

    @api.onchange('month')
    def _onchange_month_normalize(self):
        """Normalize to first day of month in UI."""
        if self.month:
            self.month = self.month.replace(day=1)

    def write(self, vals):
        if 'month' in vals and vals['month']:
            from datetime import date
            if isinstance(vals['month'], str):
                from datetime import datetime
                d = datetime.strptime(vals['month'], '%Y-%m-%d').date()
            else:
                d = vals['month']
            vals['month'] = d.replace(day=1)
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        from datetime import datetime
        for vals in vals_list:
            if 'month' in vals and vals['month']:
                if isinstance(vals['month'], str):
                    d = datetime.strptime(vals['month'], '%Y-%m-%d').date()
                else:
                    d = vals['month']
                vals['month'] = d.replace(day=1)
        return super().create(vals_list)

    @api.constrains('target_amount')
    def _check_target_amount(self):
        for rec in self:
            if rec.target_amount <= 0:
                raise ValidationError(
                    'Target amount must be greater than zero.')

    @api.constrains('commission_rate')
    def _check_commission_rate(self):
        for rec in self:
            if not (0 < rec.commission_rate <= 100):
                raise ValidationError(
                    'Commission rate must be between 0 and 100.')