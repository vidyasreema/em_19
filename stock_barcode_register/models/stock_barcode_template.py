from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from markupsafe import Markup


class StockBarcodeTemplate(models.Model):
    """Reads a vendor's own barcode by fixed positions (e.g. Firstlight).
    Tied to the barcode pattern, not to the vendor: the vendor is for reference only."""
    _name = 'stock.barcode.template'
    _description = 'Barcode Reading Template'
    _order = 'sequence, id'

    name = fields.Char('Name', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved')], default='draft', required=True, copy=False)
    partner_id = fields.Many2one('res.partner', 'Vendor (reference)')
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company)

    length = fields.Integer('Barcode Length', required=True)
    prefix = fields.Char('Fixed Prefix', help="Characters the barcode must start with.")
    # Positions are 1-based, as printed on the label specification
    product_code_start = fields.Integer('Product Code Start')
    product_code_length = fields.Integer('Product Code Length')
    qty_start = fields.Integer('Quantity Start')
    qty_length = fields.Integer('Quantity Length')
    qty_decimals = fields.Integer('Quantity Decimals')
    qty_uom_id = fields.Many2one('uom.uom', 'Quantity Unit', default=lambda self: self.env.ref('uom.product_uom_kgm', raise_if_not_found=False))
    carton_start = fields.Integer('Carton Number Start')
    carton_length = fields.Integer('Carton Number Length', help="0 = up to the end of the barcode.")
    pack_date_start = fields.Integer('Pack Date Start', help="0 = no pack date in the barcode.")
    pack_date_format = fields.Selection([('yymmdd', 'YYMMDD'), ('ddmmyy', 'DDMMYY')], default='yymmdd')

    test_barcode = fields.Char('Test Barcode', help="Paste a real barcode to see what it reads.")
    test_result = fields.Html('Test Result', compute='_compute_test_result', sanitize=False)
    sample_ids = fields.One2many('stock.barcode.template.sample', 'template_id', 'Sample Labels')

    @api.constrains('length', 'prefix', 'active', 'sample_ids')
    def _check_no_overlap(self):
        for template in self.filtered('active'):
            others = self.search([('id', '!=', template.id), ('length', '=', template.length)])
            for other in others:
                a, b = template.prefix or '', other.prefix or ''
                if a.startswith(b) or b.startswith(a):
                    raise ValidationError(_(
                        "Template %(name)s would read the same barcodes as %(other)s (same length and overlapping prefix).",
                        name=template.name, other=other.name))

    @api.constrains('length', 'product_code_start', 'product_code_length', 'qty_start', 'qty_length',
                    'carton_start', 'carton_length', 'pack_date_start')
    def _check_positions(self):
        for template in self:
            if template.length <= 0:
                raise ValidationError(_("The barcode length must be positive."))
            for start, length in ((template.product_code_start, template.product_code_length),
                                  (template.qty_start, template.qty_length),
                                  (template.carton_start, template.carton_length or 1),
                                  (template.pack_date_start, 6)):
                if start and (start < 1 or start + length - 1 > template.length):
                    raise ValidationError(_("A position of template %s is outside the barcode length.", template.name))

    def _matches(self, barcode):
        self.ensure_one()
        return bool(barcode) and len(barcode) == self.length and barcode.startswith(self.prefix or '')

    @staticmethod
    def _slice(barcode, start, length):
        return barcode[start - 1:start - 1 + length] if start else ''

    def _read(self, barcode):
        """:return: dict of read values, or False when the barcode doesn't match"""
        self.ensure_one()
        if not self._matches(barcode):
            return False
        quantity = False
        raw_qty = self._slice(barcode, self.qty_start, self.qty_length)
        if raw_qty:
            if not raw_qty.isdigit():
                return False
            quantity = int(raw_qty) / (10 ** self.qty_decimals)
        pack_date = False
        raw_date = self._slice(barcode, self.pack_date_start, 6)
        if raw_date:
            fmt = '%y%m%d' if self.pack_date_format == 'yymmdd' else '%d%m%y'
            try:
                pack_date = datetime.strptime(raw_date, fmt).date()
            except ValueError:
                return False
        carton = barcode[self.carton_start - 1:] if self.carton_start and not self.carton_length \
            else self._slice(barcode, self.carton_start, self.carton_length)
        return {
            'barcode_type': 'template',
            'template_id': self.id,
            'quantity': quantity,
            'pack_date': pack_date,
            'carton_number': carton or False,
            'product_code': self._slice(barcode, self.product_code_start, self.product_code_length) or False,
        }

    @api.model
    def _read_barcode(self, barcode):
        for template in self.search([('state', '=', 'approved')]):
            if result := template._read(barcode):
                return result
        return False

    @api.depends('test_barcode', 'length', 'prefix', 'product_code_start', 'product_code_length', 'qty_start',
                 'qty_length', 'qty_decimals', 'carton_start', 'carton_length', 'pack_date_start', 'pack_date_format')
    def _compute_test_result(self):
        for template in self:
            barcode = (template.test_barcode or '').strip()
            if not barcode:
                template.test_result = False
                continue
            result = template._read(barcode) if template.length else False
            if not result:
                template.test_result = Markup('<span class="text-danger">%s</span>') % _(
                    "No match: expected %(length)s characters starting with \"%(prefix)s\", got %(got)s characters.",
                    length=template.length, prefix=template.prefix or '', got=len(barcode))
                continue
            rows = [
                (_("Product code"), result['product_code']),
                (_("Quantity"), result['quantity']),
                (_("Carton number"), result['carton_number']),
                (_("Pack date"), result['pack_date']),
            ]
            template.test_result = Markup('<table class="table table-sm mb-0">%s</table>') % Markup().join(
                Markup('<tr><th>%s</th><td>%s</td></tr>') % (label, value if value not in (False, None) else '—')
                for label, value in rows)

    def action_approve(self):
        for template in self:
            reads = [template._read(sample.barcode) for sample in template.sample_ids]
            if len(reads) < 2:
                raise ValidationError(_("A template is approved from at least two labels with different quantities."))
            if not all(reads):
                raise ValidationError(_("Every sample label must match the template."))
            if len({r['quantity'] for r in reads}) < 2:
                raise ValidationError(_("The sample labels must have different quantities."))
            for other in self.search([('id', '!=', template.id), ('state', '=', 'approved')]):
                if any(other._matches(sample.barcode) for sample in template.sample_ids):
                    raise ValidationError(_("The samples are already read by template %s.", other.name))
        self.state = 'approved'

    def action_reset_draft(self):
        self.state = 'draft'


class StockBarcodeTemplateSample(models.Model):
    _name = 'stock.barcode.template.sample'
    _description = 'Reading Template Sample Label'

    template_id = fields.Many2one('stock.barcode.template', required=True, ondelete='cascade', index=True)
    barcode = fields.Char('Barcode', required=True)
    quantity = fields.Float('Quantity Read', compute='_compute_read', digits=(16, 3))
    carton_number = fields.Char('Carton Number Read', compute='_compute_read')
    matches = fields.Boolean('Matches', compute='_compute_read')

    @api.depends('barcode', 'template_id.length', 'template_id.prefix', 'template_id.qty_start',
                 'template_id.qty_length', 'template_id.qty_decimals', 'template_id.carton_start', 'template_id.carton_length')
    def _compute_read(self):
        for sample in self:
            result = sample.template_id._read((sample.barcode or '').strip()) if sample.template_id.length else False
            sample.matches = bool(result)
            sample.quantity = result['quantity'] if result else 0.0
            sample.carton_number = result['carton_number'] if result else False
