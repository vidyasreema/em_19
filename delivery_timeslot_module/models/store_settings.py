# -*- coding: utf-8 -*-
from datetime import timedelta

import pytz

from odoo import fields, models, api
from odoo.exceptions import ValidationError

DAY_FIELDS = [
    'shop_monday', 'shop_tuesday', 'shop_wednesday',
    'shop_thursday', 'shop_friday', 'shop_saturday', 'shop_sunday',
]


class StoreSettings(models.Model):
    _name = 'store.settings'
    _description = 'Store Settings'

    _unique_website = models.Constraint(
        'UNIQUE(website_id)',
        'A Store Settings record already exists for this website!',
    )

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

    @api.model
    def _find_for_website(self, website):
        """Settings of this website, otherwise any settings (empty if none)."""
        return self.search([('website_id', '=', website.id)], limit=1) or self.search([], limit=1)

    def _get_timezone(self):
        """Timezone of the website's company (read with sudo: website visitors
        cannot read the company contact), Asia/Dubai by default."""
        company = self.website_id.company_id or self.env.company
        try:
            return pytz.timezone(company.sudo().partner_id.tz or 'Asia/Dubai')
        except pytz.UnknownTimeZoneError:
            return pytz.timezone('Asia/Dubai')

    def _is_working_day(self, day):
        self.ensure_one()
        return bool(self[DAY_FIELDS[day.weekday()]])

    def _next_working_day(self, from_day):
        """from_day itself if it is a working day, otherwise the next one."""
        self.ensure_one()
        for offset in range(7):
            candidate = from_day + timedelta(days=offset)
            if self._is_working_day(candidate):
                return candidate
        return from_day  # no working day configured
