# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import ValidationError


class StoreSettings(models.Model):
    _name = 'store.settings'
    _description = 'Store Settings'
    _sql_constraints = [
        (
            'unique_website',
            'UNIQUE(website_id)',
            'A Store Settings record already exists for this website!'
        ),
    ]

    name = fields.Char(string='Name', default='Store Settings')
    website_id = fields.Many2one('website', string='Website')

    # ─── Operating Hours ───────────────────────────────────────
    shop_opening_time = fields.Float(
        string='Opening Time',
        default=9.0,
        help='Shop opening time in 24h format. Example: 9.0 = 9:00 AM'
    )
    shop_closing_time = fields.Float(
        string='Closing Time',
        default=22.0,
        help='Shop closing time in 24h format. Example: 22.0 = 10:00 PM'
    )

    # ─── Operating Days ────────────────────────────────────────
    shop_monday    = fields.Boolean(string='Monday',    default=True)
    shop_tuesday   = fields.Boolean(string='Tuesday',   default=True)
    shop_wednesday = fields.Boolean(string='Wednesday', default=True)
    shop_thursday  = fields.Boolean(string='Thursday',  default=True)
    shop_friday    = fields.Boolean(string='Friday',    default=True)
    shop_saturday  = fields.Boolean(string='Saturday',  default=True)
    shop_sunday    = fields.Boolean(string='Sunday',    default=True)

    # ─── Off-Hours Grace Period ────────────────────────────────
    shop_scenario2_grace_hours = fields.Float(
        string='After-Close Grace Period (hours)',
        default=2.0,
        help=(
            'Hours after closing time that still trigger the "tomorrow delivery" message '
            '(Scenario 2). Orders placed after this window trigger Scenario 3.'
        )
    )

    @api.constrains('website_id')
    def _check_unique_website(self):
        for record in self:
            existing = self.search([
                ('website_id', '=', record.website_id.id if record.website_id else False),
                ('id', '!=', record.id),
            ])
            if existing:
                raise ValidationError(
                    'A Store Settings record already exists for this website. '
                    'Please edit the existing record instead of creating a new one.'
                )

    @api.model
    def get_store_settings(self, website_id=None):
        """Always return one settings record per website."""
        domain = [('website_id', '=', website_id)] if website_id else []
        settings = self.search(domain, limit=1)
        if not settings:
            settings = self.create({
                'name': 'Store Settings',
                'website_id': website_id,
            })
        return settings