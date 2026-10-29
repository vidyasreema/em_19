from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

OUTSIDE_USAGES = ('customer', 'inventory', 'production')


class StockCountSession(models.Model):
    """Monthly count: count, compare, post. Posting writes the Counted column of
    Physical Inventory only; Apply stays standard and separate."""
    _name = 'stock.count.session'
    _description = 'Count Session'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Reference', readonly=True, copy=False, default='/')
    location_id = fields.Many2one(
        'stock.location', 'Location', tracking=True, check_company=True,
        domain="[('usage', '=', 'internal')]", readonly=False)
    employee_id = fields.Many2one(
        'hr.employee', 'Counted by', tracking=True, check_company=True,
        domain="[('stock_operation_authorized', '=', True)]")
    company_id = fields.Many2one('res.company', 'Company', required=True, default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', 'Opened by', default=lambda self: self.env.user, readonly=True)
    state = fields.Selection([
        ('draft', 'Counting'),
        ('compared', 'Comparison'),
        ('posted', 'Posted'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    date = fields.Datetime('Count Date', readonly=True, copy=False, help="Set when quantities are confirmed.")
    posted_date = fields.Datetime('Posted On', readonly=True, copy=False)
    apply_date = fields.Datetime('Applied On', readonly=True, copy=False,
                                 help="When the posted Counted quantities were applied in Physical Inventory.")
    is_baseline = fields.Boolean(
        'Baseline Count', readonly=True, copy=False,
        help="First count of the location after go-live: cartons not counted are marked sold without being treated as differences.")
    previous_session_id = fields.Many2one('stock.count.session', 'Previous Count', readonly=True, copy=False)
    line_ids = fields.One2many('stock.count.line', 'session_id', 'Products', copy=False)
    line_count = fields.Integer(compute='_compute_line_stats')
    unmatched_line_count = fields.Integer('Lines to Review', compute='_compute_line_stats')

    @api.depends('line_ids.status')
    def _compute_line_stats(self):
        for session in self:
            session.line_count = len(session.line_ids)
            session.unmatched_line_count = len(session.line_ids.filtered(lambda l: l.status not in (False, 'matched', 'baseline')))

    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        for session in sessions:
            session.name = session._make_reference()
        sessions.filtered('location_id').action_load_products()
        return sessions

    def write(self, vals):
        res = super().write(vals)
        if 'location_id' in vals:
            self.filtered(lambda s: s.state == 'draft' and s.location_id and not s.line_ids).action_load_products()
        return res

    def _make_reference(self):
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        base = 'CNT-%s' % now.strftime('%Y%m%d-%H%M')
        name, i = base, 1
        while self.search_count([('name', '=', name), ('id', '!=', self.id)], limit=1):
            i += 1
            name = '%s-%s' % (base, i)
        return name

    @api.ondelete(at_uninstall=False)
    def _unlink_except_counted(self):
        if any(session.state != 'draft' or session.line_ids.carton_ids for session in self):
            raise UserError(_("A count session is never deleted once counted. Cancel it instead."))

    # ------------------------------------------------------------------
    # Counting
    # ------------------------------------------------------------------

    def _get_location_products(self):
        """All Goods products of the location: positive, negative and zero quants,
        plus products with unsold cartons registered there."""
        self.ensure_one()
        quants = self.env['stock.quant'].sudo().search([('location_id', '=', self.location_id.id)])
        registers = self.env['stock.barcode.register'].search([
            ('location_id', '=', self.location_id.id), ('state', '=', 'unsold')])
        products = quants.product_id | registers.product_id
        return products.filtered(lambda p: p.is_storable and p.active)

    def action_load_products(self):
        for session in self:
            if session.state != 'draft' or not session.location_id:
                continue
            existing = session.line_ids.product_id
            new_products = session._get_location_products() - existing
            self.env['stock.count.line'].create([
                {'session_id': session.id, 'product_id': product.id} for product in new_products.sorted('display_name')
            ])

    def action_add_by_scan(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Add by Scan"),
            'res_model': 'stock.count.scan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.id},
        }

    def _add_scanned_barcode(self, barcode, product=None):
        """Add a product line (and its carton) from a scanned carton or product barcode."""
        self.ensure_one()
        barcode = (barcode or '').strip()
        if not barcode:
            raise UserError(_("Scan a barcode."))
        Register = self.env['stock.barcode.register']
        if not product:
            register = Register.search(['|', ('barcode', '=', barcode), ('carton_number', '=', barcode)], order='date desc', limit=1)
            product = register.product_id
        if not product:
            product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
            barcode = False  # a product barcode is not a carton
        if not product:
            parsed = self.env['stock.move.carton']._parse_gs1(barcode, self.env['product.product'])
            if parsed and parsed.get('product_code'):
                product = self.env['product.product'].search([('barcode', 'in', (parsed['product_code'], parsed['product_code'][1:]))], limit=1)
        if not product:
            raise UserError(_("No product or registered carton found for barcode %s. Add the product manually.", barcode))
        line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
        if not line:
            line = self.env['stock.count.line'].create({'session_id': self.id, 'product_id': product.id})
        if barcode:
            parsed = self.env['stock.count.carton'].parse_barcode(barcode, product.id)
            self.env['stock.count.carton'].create(dict(parsed, line_id=line.id, barcode=barcode))
        return line

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def action_confirm_quantities(self):
        for session in self:
            if session.state != 'draft':
                continue
            missing = []
            if not session.location_id:
                missing.append(_("Location"))
            if not session.employee_id:
                missing.append(_("Counted by"))
            if missing:
                raise ValidationError(_("Please fill in before confirming: %s", ", ".join(missing)))
            previous = self.search([
                ('location_id', '=', session.location_id.id), ('state', '=', 'posted'), ('id', '!=', session.id),
            ], order='date desc, id desc', limit=1)
            session.write({
                'date': fields.Datetime.now(),
                'previous_session_id': previous.id,
                'is_baseline': not previous,
                'state': 'compared',
            })
            session.line_ids._compute_comparison()
        return True

    def action_reopen(self):
        self.filtered(lambda s: s.state == 'compared').write({'state': 'draft'})
        return True

    def action_cancel(self):
        if any(session.state == 'posted' for session in self):
            raise UserError(_("A posted count session cannot be cancelled."))
        self.write({'state': 'cancel'})
        return True

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    def _get_count_label(self):
        self.ensure_one()
        date = fields.Datetime.context_timestamp(self, self.date or fields.Datetime.now())
        return '%s (%s)' % (self.name, date.strftime('%Y-%m-%d'))

    def action_post(self):
        for session in self:
            if session.state != 'compared':
                raise UserError(_("Confirm the quantities and review the comparison before posting."))
            session._post_counted_quantities()
            session._post_register()
            session.write({'state': 'posted', 'posted_date': fields.Datetime.now()})
        return True

    def _post_counted_quantities(self):
        """Write the counted quantity into the Counted column of Physical Inventory,
        documented with the session. Nothing is applied."""
        self.ensure_one()
        Quant = self.env['stock.quant'].sudo()
        for line in self.line_ids:
            quant = Quant.search([
                ('product_id', '=', line.product_id.id), ('location_id', '=', self.location_id.id),
                ('lot_id', '=', False), ('package_id', '=', False), ('owner_id', '=', False),
            ], limit=1)
            if not quant:
                # Physical Inventory only lists positive and negative quants: posting creates the line
                quant = Quant.with_context(inventory_mode=False).create({
                    'product_id': line.product_id.id,
                    'location_id': self.location_id.id,
                    'quantity': 0,
                })
            quant.write({
                'inventory_quantity': line.counted_qty,
                'inventory_quantity_set': True,
                'user_id': self.env.user.id,
                'count_session_id': self.id,
                'count_session_qty': line.counted_qty,
            })

    def _post_register(self):
        """Counted cartons stay Unsold, expected cartons not found are marked Sold,
        the open quantity is stored as a package (CNT)."""
        self.ensure_one()
        Register = self.env['stock.barcode.register']
        now = fields.Datetime.now()
        label = self._get_count_label()
        stamp = fields.Datetime.context_timestamp(self, self.date or now).strftime('%Y%m%d-%H%M')
        found = Register
        for line in self.line_ids:
            for carton in line.carton_ids:
                if not carton.register_id:
                    carton.register_id = Register.create({
                        'barcode': carton.barcode,
                        'carton_number': carton.carton_number,
                        'barcode_type': carton.barcode_type if carton.barcode_type != 'generated' else 'manual',
                        'template_id': carton.template_id.id,
                        'product_id': line.product_id.id,
                        'quantity': carton.quantity,
                        'carton_count': carton.carton_count,
                        'pack_date': carton.pack_date,
                        'pack_date_estimated': not carton.pack_date,
                        'date': self.date or now,
                        'count_session_id': self.id,
                        'employee_id': self.employee_id.id,
                        'origin_location_id': self.location_id.id,
                        'company_id': self.company_id.id,
                    })
                found |= carton.register_id
            if line.product_uom_id.compare(line.open_qty, 0) > 0:
                ref = line.product_id.default_code or str(line.product_id.id)
                line.package_id = Register.create({
                    'barcode': 'CNT-%s-%s' % (stamp, ref),
                    'barcode_type': 'package',
                    'product_id': line.product_id.id,
                    'quantity': line.open_qty,
                    'carton_count': 1,
                    'date': self.date or now,
                    'count_session_id': self.id,
                    'employee_id': self.employee_id.id,
                    'origin_location_id': self.location_id.id,
                    'company_id': self.company_id.id,
                })
                found |= line.package_id
        found.write({
            'state': 'unsold',
            'location_id': self.location_id.id,
            'last_count_session_id': self.id,
            'sale_ref': False,
            'sale_picking_id': False,
            'sold_date': False,
            'sold_count_session_id': False,
        })
        # Expected cartons not found (including the previous open package, treated as consumed)
        domain = Domain([('location_id', '=', self.location_id.id), ('state', '=', 'unsold'), ('id', 'not in', found.ids)])
        if not self.is_baseline:
            domain &= Domain('product_id', 'in', self.line_ids.product_id.ids)
        Register.search(domain).write({
            'state': 'sold',
            'sale_ref': label,
            'sold_date': now,
            'sold_count_session_id': self.id,
        })

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def action_export_xlsx(self):
        self.ensure_one()
        Export = self.env['stock.barcode.register']
        summary = [
            (_("Count Session"), self.name),
            (_("Location"), self.location_id.display_name),
            (_("Counted by"), self.employee_id.name or ''),
            (_("Count Date"), fields.Datetime.context_timestamp(self, self.date).strftime('%Y-%m-%d %H:%M') if self.date else ''),
            (_("Baseline"), _("Yes") if self.is_baseline else _("No")),
        ]
        line_header = [_("Product"), _("System Qty"), _("Counted"), _("Difference"), _("Open Qty"), _("Cartons"),
                       _("Expected"), _("Matched"), _("Out by Cartons"), _("System Outflow"), _("Outflow Difference"), _("Status"), _("Flags")]
        status_labels = dict(self.env['stock.count.line']._fields['status']._description_selection(self.env))
        line_rows = [[
            line.product_id.display_name, line.system_qty, line.counted_qty, line.difference_qty, line.open_qty,
            line.carton_count, line.expected_qty, line.matched_qty, line.out_by_cartons, line.system_outflow,
            line.outflow_difference, status_labels.get(line.status, ''), line._get_flags_label(),
        ] for line in self.line_ids]
        carton_header = [_("Product"), _("Barcode"), _("Type"), _("Quantity"), _("Cartons"), _("Pack Date"), _("Register Match"), _("Source")]
        carton_rows = [[
            carton.product_id.display_name, carton.barcode, carton.barcode_type, carton.quantity, carton.carton_count,
            carton.pack_date or '', carton.register_id.barcode if carton.register_id else _("No record"),
            carton.register_id.source_ref or '',
        ] for carton in self.line_ids.carton_ids]
        return Export._export_xlsx_action(self.name, [
            (_("Summary"), [], summary),
            (_("Products"), line_header, line_rows),
            (_("Cartons"), carton_header, carton_rows),
        ])


class StockCountLine(models.Model):
    _name = 'stock.count.line'
    _description = 'Count Line'
    _order = 'session_id, id'

    session_id = fields.Many2one('stock.count.session', required=True, index=True, ondelete='cascade')
    state = fields.Selection(related='session_id.state')
    company_id = fields.Many2one(related='session_id.company_id', store=True)
    location_id = fields.Many2one(related='session_id.location_id')
    product_id = fields.Many2one('product.product', 'Product', required=True, index=True, domain="[('is_storable', '=', True)]")
    product_uom_id = fields.Many2one(related='product_id.uom_id', string='Unit')
    carton_ids = fields.One2many('stock.count.carton', 'line_id', 'Counted Cartons')
    carton_count = fields.Integer('Cartons', compute='_compute_counted', store=True)
    carton_qty = fields.Float('Cartons Qty', compute='_compute_counted', store=True, digits='Product Unit')
    open_qty = fields.Float('Open Quantity', digits='Product Unit', help="Quantity without a carton (opened carton or cut meat), counted manually.")
    counted_qty = fields.Float('Counted', compute='_compute_counted', store=True, digits='Product Unit')
    is_counted = fields.Boolean('Counted?', compute='_compute_counted', store=True)
    photo_count = fields.Integer(compute='_compute_photo_count')
    flags = fields.Char('Flags', compute='_compute_flags')
    package_id = fields.Many2one('stock.barcode.register', 'Open Package', readonly=True)

    # Snapshot and comparison, computed on Confirm quantities
    system_qty = fields.Float('System Qty', digits='Product Unit', readonly=True)
    quant_exists = fields.Boolean('In Physical Inventory', readonly=True)
    difference_qty = fields.Float('Difference', compute='_compute_difference', digits='Product Unit')
    expected_qty = fields.Float('Expected', digits='Product Unit', readonly=True,
                                help="Cartons and open package of the previous count + cartons received since.")
    expected_carton_count = fields.Integer('Expected Cartons', readonly=True)
    matched_qty = fields.Float('Matched', digits='Product Unit', readonly=True)
    matched_carton_count = fields.Integer('Matched Cartons', readonly=True)
    unrecorded_count = fields.Integer('Unrecorded Cartons', readonly=True)
    out_by_cartons = fields.Float('Out by Cartons', digits='Product Unit', readonly=True,
                                  help="Expected − matched cartons − current open quantity.")
    system_outflow = fields.Float('System Outflow', digits='Product Unit', readonly=True,
                                  help="Sales, deliveries, consumption, adjustments and scrap since the previous count, excluding internal transfers.")
    outflow_difference = fields.Float('Outflow Difference', digits='Product Unit', readonly=True)
    status = fields.Selection([
        ('matched', 'Matched'),
        ('unrecorded', 'Unrecorded cartons'),
        ('unexplained', 'Unexplained quantity out'),
        ('no_basis', 'Balance with no basis'),
        ('baseline', 'Baseline'),
    ], readonly=True)

    @api.depends('carton_ids.quantity', 'carton_ids.carton_count', 'open_qty')
    def _compute_counted(self):
        for line in self:
            line.carton_count = sum(line.carton_ids.mapped('carton_count'))
            line.carton_qty = sum(line.carton_ids.mapped('quantity'))
            line.counted_qty = line.carton_qty + line.open_qty
            line.is_counted = bool(line.carton_ids) or bool(line.open_qty)

    @api.depends('counted_qty', 'system_qty')
    def _compute_difference(self):
        for line in self:
            line.difference_qty = line.counted_qty - line.system_qty

    def _compute_photo_count(self):
        data = self.env['ir.attachment']._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids), ('mimetype', '=like', 'image/%')],
            ['res_id'], ['__count'])
        counts = dict(data)
        for line in self:
            line.photo_count = counts.get(line.id, 0)

    @api.depends('is_counted', 'quant_exists', 'state')
    def _compute_flags(self):
        for line in self:
            line.flags = line._get_flags_label() if line.state != 'draft' else False

    def _get_flags_label(self):
        self.ensure_one()
        flags = []
        if not self.is_counted:
            flags.append(_("Posts as zero"))
        if not self.quant_exists:
            flags.append(_("New Physical Inventory line"))
        return ", ".join(flags)

    @api.constrains('product_id', 'session_id')
    def _check_unique_product(self):
        for line in self:
            if self.search_count([('session_id', '=', line.session_id.id), ('product_id', '=', line.product_id.id), ('id', '!=', line.id)], limit=1):
                raise ValidationError(_("%s is already in this count session.", line.product_id.display_name))

    def write(self, vals):
        if set(vals) & {'open_qty', 'product_id'} and any(line.state != 'draft' for line in self):
            raise UserError(_("Reopen the count to change quantities."))
        return super().write(vals)

    def _get_period_outflow(self, date_from, date_to):
        """Quantity that left the location in the period through sales, deliveries,
        consumption, adjustments and scrap (internal transfers and receipts excluded)."""
        self.ensure_one()
        location = self.session_id.location_id
        domain = [
            ('product_id', '=', self.product_id.id), ('state', '=', 'done'),
            ('date', '<=', date_to),
        ]
        if date_from:
            domain.append(('date', '>', date_from))
        Move = self.env['stock.move'].sudo()
        outflow = 0.0
        out_moves = Move.search(domain + [('location_id', '=', location.id), ('location_dest_id.usage', 'in', OUTSIDE_USAGES)])
        in_moves = Move.search(domain + [('location_dest_id', '=', location.id), ('location_id.usage', 'in', OUTSIDE_USAGES)])
        for move in (out_moves | in_moves).filtered(lambda m: not m.count_session_id):
            qty = move.product_uom._compute_quantity(move.quantity, self.product_uom_id, round=False)
            outflow += qty if move in out_moves else -qty
        # Applying a posted count only aligns the system with the count: just a manual
        # change of Counted after posting is a real movement
        outflow -= sum((out_moves | in_moves).filtered('count_session_id').mapped('count_session_diff'))
        return outflow

    def _compute_comparison(self):
        Register = self.env['stock.barcode.register']
        Quant = self.env['stock.quant'].sudo()
        for line in self:
            session = line.session_id
            quants = Quant.search([('product_id', '=', line.product_id.id), ('location_id', '=', session.location_id.id)])
            vals = {
                'system_qty': sum(quants.mapped('quantity')),
                'quant_exists': bool(quants),
            }
            matched = line.carton_ids.filtered('register_id')
            vals.update(
                matched_qty=sum(matched.mapped('quantity')),
                matched_carton_count=sum(matched.mapped('carton_count')),
                unrecorded_count=len(line.carton_ids - matched),
            )
            if session.is_baseline:
                vals.update(expected_qty=0, expected_carton_count=0, out_by_cartons=0, system_outflow=0,
                            outflow_difference=0, status='baseline')
                line.write(vals)
                continue
            previous = session.previous_session_id
            prev_line = previous.line_ids.filtered(lambda l: l.product_id == line.product_id)
            received = Register.search([
                ('product_id', '=', line.product_id.id),
                ('origin_location_id', '=', session.location_id.id),
                ('picking_id.picking_type_code', '=', 'incoming'),
                ('date', '>', previous.date), ('date', '<=', session.date),
            ])
            expected_qty = sum(prev_line.carton_ids.mapped('quantity')) + sum(prev_line.mapped('open_qty')) + sum(received.mapped('quantity'))
            expected_cartons = sum(prev_line.carton_ids.mapped('carton_count')) + len(prev_line.package_id) + sum(received.mapped('carton_count'))
            out_by_cartons = expected_qty - vals['matched_qty'] - line.open_qty
            outflow = line._get_period_outflow(previous.date, session.date)
            difference = out_by_cartons - outflow
            base = max(abs(expected_qty), abs(outflow))
            tolerance = session.company_id.barcode_register_tolerance
            uom = line.product_uom_id
            if uom.compare(vals['system_qty'], 0) and not line.is_counted and uom.is_zero(expected_qty):
                status = 'no_basis'
            elif vals['unrecorded_count']:
                status = 'unrecorded'
            elif not uom.is_zero(difference) and (not base or abs(difference) / base * 100 > tolerance):
                status = 'unexplained'
            else:
                status = 'matched'
            vals.update(expected_qty=expected_qty, expected_carton_count=expected_cartons, out_by_cartons=out_by_cartons,
                        system_outflow=outflow, outflow_difference=difference, status=status)
            line.write(vals)

    def action_open_details(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.product_id.display_name,
            'res_model': 'stock.count.line',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('stock_barcode_register.view_stock_count_line_details_form').id, 'form')],
            'target': 'new',
        }

    def action_export_xlsx(self):
        self.ensure_one()
        rows = [[
            carton.barcode, carton.barcode_type, carton.quantity, carton.carton_count, carton.pack_date or '',
            carton.register_id.barcode if carton.register_id else _("No record"), carton.register_id.source_ref or '',
        ] for carton in self.carton_ids]
        header = [_("Barcode"), _("Type"), _("Quantity"), _("Cartons"), _("Pack Date"), _("Register Match"), _("Source")]
        summary = [
            (_("Count Session"), self.session_id.name),
            (_("Location"), self.location_id.display_name),
            (_("Counted by"), self.session_id.employee_id.name or ''),
            (_("Product"), self.product_id.display_name),
            (_("Open Quantity"), self.open_qty),
            (_("Out since previous count"), self.out_by_cartons),
            (_("System Outflow"), self.system_outflow),
        ]
        return self.env['stock.barcode.register']._export_xlsx_action(
            '%s - %s' % (self.session_id.name, self.product_id.display_name),
            [(_("Summary"), [], summary), (_("Cartons"), header, rows)])


class StockCountCarton(models.Model):
    _name = 'stock.count.carton'
    _description = 'Counted Carton'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    line_id = fields.Many2one('stock.count.line', 'Count Line', required=True, index=True, ondelete='cascade')
    session_id = fields.Many2one(related='line_id.session_id', store=True, index=True)
    product_id = fields.Many2one(related='line_id.product_id', store=True)
    product_uom_id = fields.Many2one(related='line_id.product_id.uom_id', string='Unit')
    state = fields.Selection(related='line_id.session_id.state')
    barcode = fields.Char('Barcode', required=True)
    carton_number = fields.Char('Carton Number')
    product_code = fields.Char('Product Code')
    barcode_type = fields.Selection([
        ('gs1', 'GS1'),
        ('template', 'Template'),
        ('manual', 'Manual'),
        ('fixed', 'Fixed'),
        ('generated', 'Generated (REC)'),
    ], string='Type', required=True, default='manual')
    template_id = fields.Many2one('stock.barcode.template', 'Reading Template')
    quantity = fields.Float('Quantity', digits=(16, 3))
    carton_count = fields.Integer('Cartons', default=1)
    pack_date = fields.Date('Pack Date')
    register_id = fields.Many2one('stock.barcode.register', 'Register Match', readonly=True, index='btree_not_null', ondelete='set null')
    register_source = fields.Char(related='register_id.source_ref', string='Register Source')

    @api.constrains('barcode', 'carton_number', 'session_id')
    def _check_unique_in_session(self):
        for carton in self:
            domain = [('session_id', '=', carton.session_id.id), ('id', '!=', carton.id)]
            if carton.carton_number:
                domain += ['|', ('barcode', '=', carton.barcode),
                           '&', ('carton_number', '=', carton.carton_number), ('product_id', '=', carton.product_id.id)]
            else:
                domain += [('barcode', '=', carton.barcode)]
            if self.search_count(domain, limit=1):
                raise ValidationError(_("Barcode %s has already been counted in this session.", carton.barcode))

    @api.model
    def parse_barcode(self, barcode, product_id):
        return self.env['stock.move.carton'].parse_barcode(barcode, product_id)

    def _match_register(self):
        """Matching by barcode is done across all locations, since cartons sometimes move
        without a scan. A carton marked sold by an earlier count can be found again."""
        self.ensure_one()
        if self.barcode_type == 'fixed':
            return self.env['stock.barcode.register']
        domain = Domain('product_id', '=', self.product_id.id)
        domain &= Domain('carton_number', '=', self.carton_number) if self.carton_number else Domain('barcode', '=', self.barcode)
        Register = self.env['stock.barcode.register']
        return (Register.search(domain & Domain('state', '=', 'unsold'), order='date desc', limit=1)
                or Register.search(domain & Domain('sold_count_session_id', '!=', False), order='date desc', limit=1))

    def _check_editable(self):
        if any(state != 'draft' for state in self.mapped('state')):
            raise UserError(_("Reopen the count to change its cartons."))

    @api.model_create_multi
    def create(self, vals_list):
        lines = self.env['stock.count.line'].browse([vals['line_id'] for vals in vals_list if vals.get('line_id')])
        if any(line.state != 'draft' for line in lines):
            raise UserError(_("Reopen the count to change its cartons."))
        cartons = super().create(vals_list)
        for carton, vals in zip(cartons, vals_list):
            register = carton._match_register()
            if register:
                updates = {'register_id': register.id}
                if not vals.get('quantity'):
                    updates.update(quantity=register.quantity, carton_count=register.carton_count)
                if not vals.get('pack_date'):
                    updates['pack_date'] = register.pack_date
                carton.write(updates)
        return cartons

    def write(self, vals):
        if set(vals) - {'register_id'}:
            self._check_editable()
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()


class StockCountScanWizard(models.TransientModel):
    _name = 'stock.count.scan.wizard'
    _description = 'Add to Count by Scan'

    session_id = fields.Many2one('stock.count.session', required=True)
    barcode = fields.Char('Barcode')
    product_id = fields.Many2one('product.product', 'Or choose a product', domain="[('is_storable', '=', True)]")

    def action_add(self):
        self.ensure_one()
        if self.session_id.state != 'draft':
            raise UserError(_("Reopen the count to add products."))
        if self.product_id and not self.barcode:
            if not self.session_id.line_ids.filtered(lambda l: l.product_id == self.product_id):
                self.env['stock.count.line'].create({'session_id': self.session_id.id, 'product_id': self.product_id.id})
        else:
            self.session_id._add_scanned_barcode(self.barcode, self.product_id)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.session_id.id},
        }
