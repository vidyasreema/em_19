import base64
import io

import xlsxwriter

from odoo import api, fields, models

START_DATE_PARAM = 'stock_barcode_register.start_date'


class StockBarcodeRegister(models.Model):
    """One row per carton. History for comparison and audit only: never
    creates a stock move, never changes a balance or a valuation."""
    _name = 'stock.barcode.register'
    _description = 'Barcode Register'
    _order = 'date desc, id desc'
    _rec_name = 'barcode'

    barcode = fields.Char('Barcode', required=True, index='trigram', help="Full barcode as scanned, or generated.")
    carton_number = fields.Char('Carton Number', index=True, help="Carton number extracted from the barcode, used for matching.")
    barcode_type = fields.Selection([
        ('gs1', 'GS1'),
        ('template', 'Template'),
        ('manual', 'Manual'),
        ('fixed', 'Fixed'),
        ('generated', 'Generated (REC)'),
        ('package', 'Package (CNT)'),
        ('adjustment', 'Adjustment (ADJ)'),
        ('scrap', 'Scrap (SCR)'),
    ], string='Type', required=True, default='manual')

    product_id = fields.Many2one('product.product', 'Product', required=True, index=True, ondelete='restrict')
    product_tmpl_id = fields.Many2one(related='product_id.product_tmpl_id', store=True, index=True)
    product_uom_id = fields.Many2one(related='product_id.uom_id', string='Unit')
    quantity = fields.Float('Quantity', digits=(16, 3), help="Quantity in the product unit, as on the label. Negative for an adjustment decrease or a scrap.")
    carton_count = fields.Integer('Cartons', default=1, help="1 for a unique barcode; the actual count for a fixed barcode.")

    pack_date = fields.Date('Pack Date')
    pack_date_estimated = fields.Boolean('Estimated', help="Pack date was unknown, so the receipt date was used.")
    alert_date = fields.Date('Alert Date', help="Pack date + alert age. Not an official expiry date.")
    alert_date_manual = fields.Boolean('Manually Edited', help="Alert date differs from the computed one.")

    # Source operation (stored so list grouping works)
    date = fields.Datetime('Date', required=True, default=fields.Datetime.now, index=True)
    picking_id = fields.Many2one('stock.picking', 'Source Operation', index=True, ondelete='set null')
    scrap_id = fields.Many2one('stock.scrap', 'Scrap', index=True, ondelete='set null')
    move_id = fields.Many2one('stock.move', 'Stock Move', index=True, ondelete='set null', help="Adjustment move that created this row.")
    count_session_id = fields.Many2one('stock.count.session', 'Count Session', index=True, ondelete='set null',
                                       help="Count session that created this row (open package or unrecorded carton).")
    source_ref = fields.Char('Source', compute='_compute_source_ref', store=True, index=True)
    template_id = fields.Many2one('stock.barcode.template', 'Reading Template', ondelete='set null')
    origin_location_id = fields.Many2one('stock.location', 'Origin Location', index=True,
                                         help="Location where the carton entered the register.")
    last_count_session_id = fields.Many2one('stock.count.session', 'Last Count Session Seen In', index=True, ondelete='set null')
    partner_id = fields.Many2one('res.partner', 'Vendor', index=True)
    vendor_invoice_ref = fields.Char('Vendor Invoice Number')
    employee_id = fields.Many2one('hr.employee', 'Employee')
    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    location_id = fields.Many2one('stock.location', 'Last Known Location', index=True)

    state = fields.Selection([
        ('unsold', 'Unsold'),
        ('sold', 'Sold'),
    ], string='Status', required=True, default='unsold', index=True)
    sale_ref = fields.Char('Sale Reference', help="Delivery number, or date and code of the count that marked it sold.")
    sale_picking_id = fields.Many2one('stock.picking', 'Delivery', index=True, ondelete='set null')
    sold_date = fields.Datetime('Sold On')
    sold_count_session_id = fields.Many2one('stock.count.session', 'Sold by Count', index=True, ondelete='set null',
                                            help="Count session that marked this carton sold because it was not found.")

    company_id = fields.Many2one('res.company', 'Company', required=True, index=True, default=lambda self: self.env.company)

    is_past_alert = fields.Boolean('Past Alert Date', compute='_compute_is_past_alert', search='_search_is_past_alert')

    @api.depends('picking_id.name', 'count_session_id.name', 'scrap_id.name', 'move_id.reference', 'barcode_type')
    def _compute_source_ref(self):
        for rec in self:
            if rec.picking_id:
                rec.source_ref = rec.picking_id.name
            elif rec.count_session_id:
                rec.source_ref = rec.count_session_id.name
            elif rec.scrap_id:
                rec.source_ref = rec.scrap_id.name
            elif rec.barcode_type == 'adjustment':
                rec.source_ref = rec.move_id.reference or self.env._("Inventory Adjustment")
            else:
                rec.source_ref = False

    @api.depends('alert_date')
    def _compute_is_past_alert(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_past_alert = bool(rec.alert_date) and rec.alert_date < today

    def _search_is_past_alert(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        today = fields.Date.context_today(self)
        domain = [('alert_date', '<', today)]
        if (operator == '=') != value:
            domain = ['|', ('alert_date', '=', False), ('alert_date', '>=', today)]
        return domain

    # ------------------------------------------------------------------
    # Daily job: adjustments and scrap
    # ------------------------------------------------------------------

    @api.model
    def _get_start_date(self):
        """Go-live of the register: older adjustments and scraps are not logged."""
        params = self.env['ir.config_parameter'].sudo()
        value = params.get_param(START_DATE_PARAM)
        if not value:
            value = fields.Datetime.to_string(fields.Datetime.now())
            params.set_param(START_DATE_PARAM, value)
        return fields.Datetime.to_datetime(value)

    @api.model
    def _make_move_code(self, prefix, date, product):
        stamp = fields.Datetime.context_timestamp(self, date).strftime('%Y%m%d-%H%M')
        return '%s-%s-%s' % (prefix, stamp, product.default_code or product.id)

    @api.model
    def _cron_log_adjustments_and_scrap(self):
        """Log every non-sale quantity change outside a count session (Physical Inventory
        adjustments, Update Quantity, scrap) as a time reference in the register."""
        start = self._get_start_date()
        self._log_adjustments(start)
        self._log_scraps(start)

    @api.model
    def _log_adjustments(self, start):
        moves = self.env['stock.move'].sudo().search([
            ('is_inventory', '=', True), ('state', '=', 'done'), ('scrap_id', '=', False),
            ('barcode_register_logged', '=', False), ('date', '>=', start),
            ('product_id.is_storable', '=', True),
        ], order='date, id')
        vals_list = []
        for move in moves:
            product = move.product_id
            increase = move.location_dest_id.usage == 'internal'
            location = move.location_dest_id if increase else move.location_id
            quantity = move.product_uom._compute_quantity(move.quantity, product.uom_id, round=False)
            if move.count_session_id:
                # Applied from a posted count session: already recorded, except a manual change after posting
                quantity = move.count_session_diff
                if product.uom_id.is_zero(quantity):
                    continue
            elif not increase:
                quantity = -quantity
            vals_list.append({
                'barcode': self._make_move_code('ADJ', move.date, product),
                'barcode_type': 'adjustment',
                'product_id': product.id,
                'quantity': quantity,
                'carton_count': 1,
                'date': move.date,
                'move_id': move.id,
                'location_id': location.id,
                'origin_location_id': location.id,
                'user_id': move.create_uid.id,
                'company_id': move.company_id.id,
            })
        self.sudo().create(vals_list)
        moves.write({'barcode_register_logged': True})

    @api.model
    def _log_scraps(self, start):
        scraps = self.env['stock.scrap'].sudo().search([
            ('state', '=', 'done'), ('barcode_register_logged', '=', False), ('date_done', '>=', start),
            ('product_id.is_storable', '=', True),
        ], order='date_done, id')
        self.sudo().create([{
            'barcode': self._make_move_code('SCR', scrap.date_done, scrap.product_id),
            'barcode_type': 'scrap',
            'product_id': scrap.product_id.id,
            'quantity': -scrap.product_uom_id._compute_quantity(scrap.scrap_qty, scrap.product_id.uom_id, round=False),
            'carton_count': 1,
            'date': scrap.date_done,
            'scrap_id': scrap.id,
            'location_id': scrap.location_id.id,
            'origin_location_id': scrap.location_id.id,
            'user_id': scrap.create_uid.id,
            'company_id': scrap.company_id.id,
        } for scrap in scraps])
        scraps.write({'barcode_register_logged': True})

    # ------------------------------------------------------------------
    # Export (evidence for weight disputes)
    # ------------------------------------------------------------------

    @api.model
    def _export_xlsx_action(self, title, sheets):
        """Build an xlsx file and return a download action.

        :param sheets: list of (sheet name, header, rows); an empty header means
                       rows are (label, value) pairs
        """
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True, 'default_date_format': 'yyyy-mm-dd'})
        bold = workbook.add_format({'bold': True, 'bg_color': '#DDE4EE', 'border': 1})
        for sheet_name, header, rows in sheets:
            sheet = workbook.add_worksheet(sheet_name[:31])
            row_index = 0
            if header:
                for col, label in enumerate(header):
                    sheet.write(0, col, label, bold)
                    sheet.set_column(col, col, max(12, len(str(label)) + 2))
                row_index = 1
            for row in rows:
                for col, value in enumerate(row):
                    if header:
                        sheet.write(row_index, col, value)
                    else:
                        sheet.write(row_index, col, value, bold if col == 0 else None)
                row_index += 1
            if not header:
                sheet.set_column(0, 1, 28)
        workbook.close()
        filename = '%s.xlsx' % title.replace('/', '-')
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(output.getvalue()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'download',
        }
