from odoo import fields, models, _
from odoo.exceptions import UserError, ValidationError
import json


class PosOrder(models.Model):
    _inherit = 'pos.order'

    all_raw_material_ids = fields.Many2many(
        'pos.order.line.raw.material',
        string='Raw Materials Used',
        compute='_compute_all_raw_material_ids',
        help="Every raw material recorded across all order lines, "
             "aggregated for display on the order form.",
    )

    def _compute_all_raw_material_ids(self):
        for order in self:
            order.all_raw_material_ids = order.lines.mapped('raw_material_ids')

    manufacturing_order_ids = fields.One2many(
        'mrp.production',
        'pos_order_id',
        string='Manufacturing Orders',
    )
    manufacturing_order_count = fields.Integer(
        string='Manufacturing Order Count',
        compute='_compute_manufacturing_order_count',
    )
    raw_material_note_generated = fields.Boolean(
        string='Raw Material Note Generated',
        default=False,
        copy=False,
        help="Set once the raw material summary has been written to the "
             "internal note, so re-saving the order does not append the "
             "same note again.",
    )

    def _compute_manufacturing_order_count(self):
        # sudo: a POS user without Manufacturing rights must still be able
        # to open a POS order in the backend.
        for order in self:
            order.manufacturing_order_count = len(
                order.sudo().manufacturing_order_ids
            )

    def action_view_manufacturing_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('mrp.mrp_production_action')
        action['domain'] = [('id', 'in', self.sudo().manufacturing_order_ids.ids)]
        action['context'] = {}
        return action

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def _process_saved_order(self, draft):
        result = super()._process_saved_order(draft)
        if not draft and self.state != 'cancel':
            # POS order sync runs as the cashier, who normally has no
            # Manufacturing rights: creating an MO also creates an
            # mrp.production.group record, which requires Manufacturing/User
            # and otherwise blocks the sale with an AccessError.
            # Everything below therefore runs as sudo, with the real user
            # carried in the context so chatter messages and activities
            # still point at a person rather than OdooBot.
            order = self.sudo().with_context(
                pos_mfg_acting_user_id=self.env.user.id
            )
            order._create_manufacturing_orders()
            order._generate_raw_material_note()
            order._handle_manufacturing_order_refunds()
        return result

    def _get_acting_user(self):
        """The real user behind this sync, not the superuser that sudo()
        would otherwise report."""
        user_id = self.env.context.get('pos_mfg_acting_user_id')
        if user_id:
            user = self.env['res.users'].browse(user_id).exists()
            if user:
                return user
        return self.user_id or self.env.user

    def _post_manufacturing_message(self, record, body):
        """Posts chatter as the cashier who triggered the sync. Without an
        explicit author, sudo() makes every message appear as OdooBot."""
        record.message_post(
            body=body,
            author_id=self._get_acting_user().partner_id.id,
        )

    # ------------------------------------------------------------------
    # Manufacturing Order creation
    # ------------------------------------------------------------------

    def _create_manufacturing_orders(self):
        self.ensure_one()
        Production = self.env['mrp.production'].sudo()
        for line in self.lines:
            if not line.product_id.is_manufacture_route:
                continue
            if not line.raw_material_ids:
                continue
            # Refund lines carry a negative quantity and must never
            # produce a Manufacturing Order of their own.
            if line.qty <= 0:
                continue
            # This order can be saved more than once (re-sync, edit, or an
            # invoice created afterwards). Without this guard every save
            # would create another MO for the same line.
            if line.manufacturing_order_ids:
                continue

            move_raw_vals = [
                (0, 0, {
                    'product_id': material.product_id.id,
                    'product_uom_qty': material.qty,
                    'product_uom': material.uom_id.id,
                })
                for material in line.raw_material_ids
            ]

            Production.create({
                'product_id': line.product_id.id,
                'product_qty': line.qty,
                'product_uom_id': line.product_id.uom_id.id,
                'move_raw_ids': move_raw_vals,
                'pos_order_id': self.id,
                'pos_order_line_id': line.id,
                'origin': self.name,
                'state': 'draft',
            })

    # ------------------------------------------------------------------
    # Internal note
    # ------------------------------------------------------------------

    def _get_internal_notes_json(self):
        self.ensure_one()

        if not self.internal_note:
            return []

        try:
            notes = json.loads(self.internal_note)

            if isinstance(notes, list):
                return notes

        except (json.JSONDecodeError, TypeError):
            pass

        # Existing old plain-text note
        return [{
            'text': self.internal_note,
            'colorIndex': 0,
        }]

    def _generate_raw_material_note(self):
        self.ensure_one()

        # Same re-save protection as the Manufacturing Orders above.
        if self.raw_material_note_generated:
            return

        blocks = []

        for line in self.lines:
            if not line.raw_material_ids:
                continue

            header = (
                f"{line.product_id.display_name} "
                f"{line.qty}{line.product_id.uom_id.name}"
            )

            material_lines = [
                f"|-{m.product_id.display_name} "
                f"{m.qty}{m.product_id.uom_id.name}"
                for m in line.raw_material_ids
            ]

            blocks.append("\n".join([header] + material_lines))

        if not blocks:
            return

        note_text = "\n----------------\n".join(blocks)

        existing_notes = self._get_internal_notes_json()

        existing_notes.append({
            'text': note_text,
            'colorIndex': 0,
        })

        self.internal_note = json.dumps(existing_notes)
        self.raw_material_note_generated = True

    # ------------------------------------------------------------------
    # Refund handling
    # ------------------------------------------------------------------

    def _handle_manufacturing_order_refunds(self):
        """Reacts to refunded lines by reversing their linked Manufacturing
        Order, differently depending on how far that MO has progressed:

        - Draft: reduce the quantity, or cancel outright if the whole line
          was refunded. Nothing has been reserved or consumed yet.
        - Confirmed: components are reserved but not consumed, so a full
          refund cancels the MO and releases the reservation. Partial
          refunds, and anything already started, are flagged for manual
          review instead.
        - Done: an Unbuild Order is created and validated automatically,
          returning the raw materials to stock.

        Whether each of these also raises a To-Do activity is controlled by
        the POS config's 'Create Review Activity' setting.

        Guarded so it can never break a normal checkout even if
        'refunded_orderline_id' doesn't exist on this Odoo version.
        """
        self.ensure_one()
        if 'refunded_orderline_id' not in self.env['pos.order.line']._fields:
            return

        for line in self.lines:
            original_line = line.refunded_orderline_id
            if not original_line or not original_line.product_id.is_manufacture_route:
                continue

            remaining_to_refund = abs(line.qty)
            if not remaining_to_refund:
                continue

            active_mos = original_line.manufacturing_order_ids.filtered(
                lambda m: m.state != 'cancel'
            )
            for mo in active_mos:
                if remaining_to_refund <= 0:
                    break
                if mo.state == 'draft':
                    remaining_to_refund -= self._reverse_draft_manufacturing_order(
                        mo, remaining_to_refund
                    )
                elif mo.state == 'done':
                    remaining_to_refund -= self._reverse_done_manufacturing_order(
                        mo, remaining_to_refund
                    )
                else:
                    remaining_to_refund -= self._reverse_confirmed_manufacturing_order(
                        mo, remaining_to_refund
                    )

    def _reverse_draft_manufacturing_order(self, mo, refunded_qty):
        """Cancels or shrinks a not-yet-reviewed MO. Returns the quantity
        actually absorbed from `refunded_qty`."""
        original_qty = mo.product_qty
        consumed = min(refunded_qty, original_qty)
        remaining_qty = original_qty - consumed

        if remaining_qty <= 0:
            note = _(
                "Cancelled automatically: linked POS order %s was refunded "
                "before this Manufacturing Order was reviewed."
            ) % self.name
            mo.action_cancel()
        else:
            ratio = remaining_qty / original_qty if original_qty else 0
            mo.product_qty = remaining_qty
            for move in mo.move_raw_ids:
                move.product_uom_qty = move.product_uom_qty * ratio
            note = _(
                "Quantity reduced from %(old)s to %(new)s: POS order "
                "%(order)s refunded %(qty)s unit(s) before this "
                "Manufacturing Order was reviewed."
            ) % {
                'old': original_qty,
                'new': remaining_qty,
                'order': self.name,
                'qty': consumed,
            }

        self._post_manufacturing_message(mo, note)
        self._create_manufacturing_review_activity(mo, note, automated=True)
        return consumed

    def _reverse_confirmed_manufacturing_order(self, mo, refunded_qty):
        """Cancels a confirmed MO when the whole line was refunded and
        production has not physically started. Confirming an MO only
        reserves components, so cancelling releases the reservation
        without moving any stock.

        Anything already started or partially consumed is left alone and
        flagged for manual review instead: a worker may have taken the
        components to the bench already.
        """
        started = (
            mo.state == 'progress'
            or mo.qty_producing
            or any(move.picked for move in mo.move_raw_ids)
        )
        if started:
            self._flag_manufacturing_order_for_review(mo, refunded_qty)
            return refunded_qty

        # Partial refunds would need the reserved component quantities
        # rescaled, which Odoo does not do automatically once an MO is
        # confirmed. Those stay manual.
        if refunded_qty < mo.product_qty:
            self._flag_manufacturing_order_for_review(mo, refunded_qty)
            return refunded_qty

        consumed = min(refunded_qty, mo.product_qty)
        note = _(
            "Cancelled automatically: linked POS order %s was refunded in "
            "full. No components had been consumed, so the reservation has "
            "been released."
        ) % self.name
        mo.action_cancel()
        self._post_manufacturing_message(mo, note)
        self._create_manufacturing_review_activity(mo, note, automated=True)
        return consumed

    def _reverse_done_manufacturing_order(self, mo, refunded_qty):
        """Creates an Unbuild Order for a completed MO and validates it
        immediately, returning the raw materials to stock without manual
        intervention. If validation fails the unbuild is left in draft and
        the activity explains why."""
        # Unbuilds already raised against this MO (draft ones included)
        # must be deducted, otherwise a re-synced refund would propose
        # unbuilding the same production twice.
        already_unbuilt = sum(mo.unbuild_ids.mapped('product_qty'))
        consumed = min(refunded_qty, mo.qty_produced - already_unbuilt)
        if consumed <= 0:
            return 0

        unbuild_vals = {
            'product_id': mo.product_id.id,
            'product_qty': consumed,
            'product_uom_id': mo.product_uom_id.id,
            'mo_id': mo.id,
            'location_id': mo.location_dest_id.id,
            'location_dest_id': mo.location_src_id.id,
        }

        # Odoo refuses to validate an unbuild of a tracked product without
        # a lot. Pre-fill it when the MO produced exactly one lot so the
        # manufacturing manager does not have to hunt for it.
        if mo.product_id.tracking != 'none' and len(mo.lot_producing_ids) == 1:
            unbuild_vals['lot_id'] = mo.lot_producing_ids.id

        unbuild = self.env['mrp.unbuild'].sudo().create(unbuild_vals)

        validated = False
        failure_reason = False
        try:
            # action_validate() refuses when on-hand is short and returns the
            # insufficient-quantity wizard instead of unbuilding. Confirming
            # that wizard in the UI simply calls action_unbuild(), so we call
            # it directly: these products are sold at POS before their
            # Manufacturing Order is produced, so on-hand is routinely
            # negative and the availability check would block every refund.
            unbuild.action_unbuild()
            validated = unbuild.state == 'done'
        except (UserError, ValidationError) as error:
            failure_reason = str(error)

        if validated:
            note = _(
                "Unbuild Order %(unbuild)s created and validated automatically: "
                "POS order %(order)s refunded %(qty)s unit(s) of a completed "
                "Manufacturing Order. Raw materials have been returned to stock."
            ) % {'unbuild': unbuild.name, 'order': self.name, 'qty': consumed}
        else:
            note = _(
                "Unbuild Order %(unbuild)s was created for POS order %(order)s "
                "(%(qty)s unit(s) refunded) but could not be validated "
                "automatically: %(reason)s. It has been left in draft — please "
                "review and validate it manually."
            ) % {
                'unbuild': unbuild.name,
                'order': self.name,
                'qty': consumed,
                'reason': failure_reason or _("unknown error"),
            }

        self._post_manufacturing_message(mo, note)
        # A validated unbuild needed no human input; a failed one does.
        self._create_manufacturing_review_activity(
            unbuild, note, automated=validated
        )
        return consumed

    def _flag_manufacturing_order_for_review(self, mo, refunded_qty):
        note = _(
            "POS order %(order)s refunded %(qty)s unit(s) of a "
            "manufactured product whose Manufacturing Order is already "
            "%(state)s and cannot be reversed automatically — production "
            "has started, or only part of the line was refunded. Please "
            "review manually."
        ) % {'order': self.name, 'qty': refunded_qty, 'state': mo.state}
        self._post_manufacturing_message(mo, note)
        self._create_manufacturing_review_activity(mo, note)

    def _create_manufacturing_review_activity(self, record, note, automated=False):
        """Raises the To-Do activity, subject to the POS config setting.

        `automated` marks cases the module already handled by itself — a
        cancelled Manufacturing Order, a validated Unbuild Order — which
        only produce an activity when the setting is 'always'.

        Assignee, in order of preference: the POS config's reviewer, the
        record's own responsible, the MO behind an unbuild, then the
        cashier. Odoo's activity_schedule has no fallback of its own —
        leave user_id out and the activity is created with no assignee, so
        it never shows up in anyone's activity list.
        """
        mode = self.config_id.mfg_activity_creation or 'review_only'
        if mode == 'never':
            return
        if mode == 'review_only' and automated:
            return

        responsible = self.config_id.mfg_review_user_id

        if not responsible and 'user_id' in record._fields:
            responsible = record.user_id
        if not responsible and 'mo_id' in record._fields:
            responsible = record.mo_id.user_id
        if not responsible:
            # _get_acting_user, not env.user: under sudo the latter is
            # OdooBot, whose activity list nobody ever opens.
            responsible = self._get_acting_user()

        record.activity_schedule(
            'mail.mail_activity_data_todo',
            summary=_('POS refund requires manufacturing review'),
            note=note,
            user_id=responsible.id,
        )