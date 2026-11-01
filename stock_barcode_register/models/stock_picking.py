from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    employee_id = fields.Many2one(
        'hr.employee', 'Employee', copy=False, tracking=True, check_company=True,
        domain="[('stock_operation_authorized', '=', True)]",
        help="Authorized employee who received, transferred or delivered the goods.")
    vendor_invoice_ref = fields.Char('Vendor Invoice Number', copy=False, tracking=True)
    vendor_barcode_hint = fields.Selection(related='partner_id.commercial_partner_id.barcode_expected_type', string='Expected Barcode Type')
    vendor_scan_requirement = fields.Selection(related='partner_id.commercial_partner_id.barcode_scan_requirement', string='Carton Scan Requirement')
    scanned_carton_count = fields.Integer('Scanned Cartons', compute='_compute_scanned_carton_count')

    def _compute_scanned_carton_count(self):
        data = self.env['stock.move.carton']._read_group([('picking_id', 'in', self.ids)], ['picking_id'], ['carton_count:sum'])
        counts = {picking.id: total for picking, total in data}
        for picking in self:
            picking.scanned_carton_count = counts.get(picking.id, 0)

    def action_open_scanned_cartons(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Cartons: %s", self.name),
            'res_model': 'stock.move.carton',
            'view_mode': 'list',
            'views': [(self.env.ref('stock_barcode_register.view_stock_move_carton_picking_list').id, 'list')],
            'domain': [('picking_id', '=', self.id)],
            'context': {'create': False},
        }

    def _get_lines_without_cartons(self):
        self.ensure_one()
        return self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel') and not m.carton_ids
                                      and not m.product_uom.is_zero(m.quantity))

    @api.depends('picking_type_id', 'partner_id')
    def _compute_location_id(self):
        # Locations start empty on purpose to avoid wrong defaults (receipt destination,
        # transfer source and destination). Only for new operations opened from the
        # Receipts / Internal Transfers menus; pickings created by code keep the standard.
        previous = {picking: (picking.location_id, picking.location_dest_id) for picking in self}
        super()._compute_location_id()
        if not self.env.context.get('restricted_picking_type_code') \
                or not self.env.user.has_group('stock.group_stock_multi_locations'):
            return
        for picking in self:
            if picking._origin.id or picking.return_id or picking.state in ('cancel', 'done'):
                continue
            location, location_dest = previous[picking]
            if picking.picking_type_code == 'incoming':
                picking.location_dest_id = location_dest
            elif picking.picking_type_code == 'internal':
                picking.location_id = location
                picking.location_dest_id = location_dest

    def _get_employee_label(self):
        return {
            'incoming': _("Received by"),
            'internal': _("Transferred by"),
            'outgoing': _("Delivered by"),
        }.get(self.picking_type_code)

    def _get_barcode_register_missing_fields(self):
        """Return the labels of the required header fields left empty on this operation."""
        self.ensure_one()
        code = self.picking_type_code
        missing = []
        if code in ('incoming', 'internal', 'outgoing') and not self.employee_id:
            missing.append(self._get_employee_label())
        if code == 'incoming':
            if not self.partner_id:
                missing.append(_("Vendor"))
            if not self.vendor_invoice_ref:
                missing.append(_("Vendor Invoice Number"))
            if not self.location_dest_id:
                missing.append(_("Destination Location"))
        elif code == 'internal':
            if not self.location_id:
                missing.append(_("Source Location"))
            if not self.location_dest_id:
                missing.append(_("Destination Location"))
        return missing

    def _check_barcode_register_header(self):
        errors = []
        for picking in self:
            missing = picking._get_barcode_register_missing_fields()
            if missing:
                errors.append(_("%(picking)s: %(fields)s", picking=picking.display_name, fields=", ".join(missing)))
            elif picking.picking_type_code == 'internal' and picking.location_id == picking.location_dest_id:
                errors.append(_("%(picking)s: the source and destination locations must be different.", picking=picking.display_name))
        if errors:
            raise ValidationError(_("Please complete the following before validating:\n%s", "\n".join(errors)))

    def _check_barcode_register_tolerance(self):
        """Store each line's difference at validation and require a note above tolerance."""
        errors = []
        for move in self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            difference = move._get_live_barcode_difference()
            move.barcode_difference_validated = difference
            if move._is_above_tolerance(difference) and not move.barcode_note:
                errors.append(_("%(picking)s - %(product)s: %(difference).2f%%",
                                picking=move.picking_id.display_name, product=move.product_id.display_name,
                                difference=difference))
        if errors:
            raise ValidationError(_(
                "A note is required on lines whose difference exceeds the tolerance:\n%s", "\n".join(errors)))

    def _check_vendor_scan_requirement(self):
        errors = []
        for picking in self.filtered(lambda p: p.picking_type_code == 'incoming' and p.vendor_scan_requirement == 'required'):
            if moves := picking._get_lines_without_cartons():
                errors.append(_("%(picking)s: %(products)s", picking=picking.display_name,
                                products=", ".join(moves.product_id.mapped('display_name'))))
        if errors:
            raise ValidationError(_(
                "This vendor requires carton details on every line. Scan the cartons, or add a carton "
                "without a barcode to generate one:\n%s", "\n".join(errors)))

    def button_validate(self):
        # POS and other automatic flows call _action_done directly and are not affected.
        to_check = self.filtered(lambda p: p.state not in ('done', 'cancel'))
        to_check._check_barcode_register_header()
        to_check._check_barcode_register_tolerance()
        to_check._check_vendor_scan_requirement()
        warn = {
            picking: picking._get_lines_without_cartons().product_id
            for picking in to_check.filtered(lambda p: p.picking_type_code == 'incoming' and p.vendor_scan_requirement == 'warning')
        }
        res = super().button_validate()
        done = to_check.filtered(lambda p: p.state == 'done')
        done.filtered(lambda p: p.picking_type_code == 'incoming')._schedule_difference_activity()
        for picking, products in warn.items():
            if picking.state == 'done' and products:
                picking.message_post(body=_("Posted with lines without carton details: %s", ", ".join(products.mapped('display_name'))))
                self.env.user._bus_send('simple_notification', {
                    'type': 'warning',
                    'title': _("Lines without carton details"),
                    'message': _("%(picking)s was posted, but some lines have no carton details: %(products)s",
                                 picking=picking.name, products=", ".join(products.mapped('display_name'))),
                })
        return res

    def _has_sales_document(self):
        """Sales order (sale_stock), POS order, or a return: no follow-up needed."""
        self.ensure_one()
        if self.return_id or self.location_dest_id.usage != 'customer':
            return True
        for fname in ('sale_id', 'pos_order_id', 'pos_session_id'):
            if fname in self._fields and self[fname]:
                return True
        return False

    def _schedule_followup_activity(self, summary, note):
        self.ensure_one()
        for user in self.company_id.barcode_register_followup_user_ids or self.env.user:
            self.activity_schedule('mail.mail_activity_data_todo', summary=summary, note=note, user_id=user.id)

    def action_export_cartons_xlsx(self):
        self.ensure_one()
        summary = [
            (_("Operation"), self.name),
            (_("Vendor") if self.picking_type_code == 'incoming' else _("Contact"), self.partner_id.display_name or ''),
            (_("Vendor Invoice Number"), self.vendor_invoice_ref or ''),
            (self._get_employee_label() or _("Employee"), self.employee_id.name or ''),
            (_("Date"), fields.Datetime.context_timestamp(self, self.date_done or self.scheduled_date).strftime('%Y-%m-%d %H:%M')),
        ]
        header = [_("Product"), _("Barcode"), _("Type"), _("Quantity"), _("Unit"), _("Cartons"), _("Pack Date"),
                  _("Estimated"), _("Alert Date"), _("Manually Edited")]
        rows = [[
            carton.product_id.display_name, carton.barcode, carton.barcode_type, carton.quantity, carton.product_uom_id.name,
            carton.carton_count, carton.pack_date or '', _("Yes") if carton.pack_date_estimated else '',
            carton.alert_date or '', _("Yes") if carton.alert_date_manual else '',
        ] for carton in self.move_ids.carton_ids]
        registers = self.env['stock.barcode.register'].search([('picking_id', '=', self.id), ('id', 'not in', self.move_ids.carton_ids.register_id.ids)])
        rows += [[
            row.product_id.display_name, row.barcode, row.barcode_type, row.quantity, row.product_uom_id.name, row.carton_count,
            row.pack_date or '', _("Yes") if row.pack_date_estimated else '', row.alert_date or '', '',
        ] for row in registers]
        return self.env['stock.barcode.register']._export_xlsx_action(self.name, [
            (_("Summary"), [], summary), (_("Cartons"), header, rows)])

    def action_create_product(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("New Product"),
            'res_model': 'stock.barcode.product.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id},
        }

    def _schedule_difference_activity(self):
        for picking in self:
            moves = picking.move_ids.filtered(lambda m: m.state == 'done' and m._is_above_tolerance(m.barcode_difference_validated))
            if not moves:
                continue
            lines = Markup().join(
                Markup("<li>%s: %.2f%% (%s)</li>") % (move.product_id.display_name, move.barcode_difference_validated, move.barcode_note or '')
                for move in moves
            )
            note = Markup("<p>%s</p><ul>%s</ul>") % (
                _("Vendor invoice %s: differences above tolerance to settle by a credit note or a correction.", picking.vendor_invoice_ref or ''),
                lines,
            )
            picking._schedule_followup_activity(_("Receipt difference above tolerance"), note)

    def _action_done(self):
        res = super()._action_done()
        self.filtered(lambda p: p.state == 'done')._barcode_register_on_done()
        return res

    def _barcode_register_on_done(self):
        for picking in self:
            if picking.picking_type_code == 'incoming' and picking.location_id.usage == 'supplier':
                picking._barcode_register_receive()
            elif picking.picking_type_code == 'internal':
                for carton in picking.move_ids.carton_ids.filtered('register_id'):
                    carton.register_id.location_id = carton.move_id.location_dest_id
            elif picking.picking_type_code == 'outgoing':
                if not picking._has_sales_document():
                    picking._schedule_followup_activity(
                        _("Delivery without a linked sales document"),
                        _("Delivery %s has no linked sales order or invoice: follow up and record it in accounting.", picking.name))
                registers = picking.move_ids.carton_ids.register_id
                registers.filtered(lambda r: r.state == 'unsold').write({
                    'state': 'sold',
                    'sale_ref': picking.name,
                    'sale_picking_id': picking.id,
                    'sold_date': picking.date_done,
                })

    def _barcode_register_receive(self):
        """Receipt: every scanned carton becomes a register row; any quantity received
        without a scan gets one row with a generated REC barcode."""
        self.ensure_one()
        Register = self.env['stock.barcode.register']
        Carton = self.env['stock.move.carton']
        common = {
            'date': self.date_done,
            'picking_id': self.id,
            'partner_id': self.partner_id.id,
            'vendor_invoice_ref': self.vendor_invoice_ref,
            'employee_id': self.employee_id.id,
            'company_id': self.company_id.id,
        }
        for move in self.move_ids.filtered(lambda m: m.state == 'done'):
            product = move.product_id
            for carton in move.carton_ids.filtered(lambda c: not c.register_id):
                carton._system_write({'register_id': Register.create(dict(common, **{
                    'barcode': carton.barcode,
                    'carton_number': carton.carton_number,
                    'barcode_type': carton.barcode_type,
                    'product_id': product.id,
                    'quantity': carton.quantity,
                    'carton_count': carton.carton_count,
                    'pack_date': carton.pack_date,
                    'pack_date_estimated': carton.pack_date_estimated,
                    'alert_date': carton.alert_date,
                    'alert_date_manual': carton.alert_date_manual,
                    'template_id': carton.template_id.id,
                    'location_id': move.location_dest_id.id,
                    'origin_location_id': move.location_dest_id.id,
                })).id})
            received = move.product_uom._compute_quantity(move.quantity, product.uom_id, round=False)
            remainder = received - sum(move.carton_ids.mapped('quantity'))
            if product.uom_id.compare(remainder, 0) > 0:
                receipt_date = fields.Date.context_today(self, self.date_done)
                alert_days = product.product_tmpl_id._get_barcode_alert_days(self.company_id)
                Register.create(dict(common, **{
                    'barcode': Carton._get_generated_barcode(product, receipt_date),
                    'barcode_type': 'generated',
                    'product_id': product.id,
                    'quantity': product.uom_id.round(remainder),
                    'carton_count': 1,
                    'pack_date': receipt_date,
                    'pack_date_estimated': True,
                    'alert_date': receipt_date + timedelta(days=alert_days) if alert_days else False,
                    'location_id': move.location_dest_id.id,
                    'origin_location_id': move.location_dest_id.id,
                }))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_scanned_cartons(self):
        if self.move_ids.carton_ids:
            raise UserError(_("An operation with scanned cartons cannot be deleted. Cancel it instead."))
