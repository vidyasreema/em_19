# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError
from markupsafe import Markup


class ProductUomMigrationWizard(models.TransientModel):
    _name = "product.uom.migration.wizard"
    _description = "Product UoM Migration Wizard"

    product_ids = fields.Many2many(
        "product.template",
        string="Products to Migrate",
        required=True,
    )
    new_uom_id = fields.Many2one(
        "uom.uom",
        string="New Unit of Measure",
        required=True,
    )
    conversion_factor = fields.Float(
        string="Conversion Factor (1 old unit = ? new unit)",
        default=1.0,
        required=True,
        help="How many units of the NEW UoM equal 1 unit of the OLD UoM. "
             "Example: if 1 Piece = 0.5 kg, enter 0.5. If the units are "
             "equivalent (e.g. Unit = kg for your business), enter 1."
    )
    allow_negative_stock = fields.Boolean(
        string="Allow Negative Stock Migration",
        default=False,
        help="If checked, products with negative on-hand quantity will be "
             "migrated too, carrying the same negative quantity over to the "
             "new product instead of being skipped. Use with care — this "
             "means the new product also starts with a stock shortfall."
    )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def action_confirm_migration(self):
        self.ensure_one()
        if not self.product_ids:
            raise UserError(_("Please select at least one product to migrate."))
        if not self.new_uom_id:
            raise UserError(_("Please select the new Unit of Measure."))
        if self.conversion_factor <= 0:
            raise UserError(_("The conversion factor must be greater than zero."))

        new_products = self.env["product.template"]
        skipped = []
        failed = []

        for product in self.product_ids:
            if product.uom_id == self.new_uom_id:
                skipped.append(_("'%s' already uses this Unit of Measure.") % product.display_name)
                continue

            # Check every variant, not the template total: one variant at -5
            # and another at +10 would otherwise hide the negative one.
            negative_variants = product.product_variant_ids.filtered(lambda v: v.qty_available < 0)
            if negative_variants and not self.allow_negative_stock:
                details = ", ".join(
                    "%s (%.2f)" % (v.display_name, v.qty_available) for v in negative_variants
                )
                skipped.append(_(
                    "'%s' has negative stock: %s. Correct the stock first, or "
                    "check 'Allow Negative Stock Migration' to carry it over."
                ) % (product.display_name, details))
                continue

            open_orders = self._get_open_sale_orders(product)
            if open_orders:
                skipped.append(_(
                    "'%s' has sale orders still to be delivered/invoiced: %s. "
                    "Deliver and invoice (or cancel) them first, then migrate."
                ) % (product.display_name, ", ".join(open_orders.mapped("name"))))
                continue

            try:
                new_products |= self._migrate_single_product(product)
            except UserError as e:
                failed.append(str(e))

        messages = []
        if skipped:
            messages.append(_("Skipped:\n%s") % "\n".join(skipped))
        if failed:
            messages.append(_("Failed:\n%s") % "\n".join(failed))
        summary = "\n\n".join(messages)

        if not new_products:
            raise UserError(summary or _("No products were migrated."))

        result_action = {
            "type": "ir.actions.act_window",
            "name": _("Migrated Products"),
            "res_model": "product.template",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "domain": [("id", "in", new_products.ids)],
            "target": "current",
        }

        if not summary:
            return result_action

        # message_post() works on ONE record only (it calls ensure_one()).
        html_summary = Markup("<br/>").join(summary.split("\n"))
        for new_product in new_products:
            new_product.message_post(body=html_summary)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Migration finished with warnings"),
                "message": summary,
                "type": "warning",
                "sticky": True,
                "next": result_action,
            },
        }

    # ------------------------------------------------------------------
    # Per-product migration, wrapped in a savepoint so a failure on one
    # product rolls back cleanly without corrupting that product's data.
    # ------------------------------------------------------------------
    def _migrate_single_product(self, product):
        cr = self.env.cr
        savepoint_name = "product_uom_migration_%s" % product.id
        cr.execute("SAVEPOINT %s" % savepoint_name)
        try:
            pos_flag = product.available_in_pos if "available_in_pos" in product._fields else False
            new_product = self._create_replacement_product(product)
            variant_map = self._map_variants(product, new_product)

            # Read identifiers and quantities BEFORE anything is moved/archived.
            variant_data = []
            for old_variant, new_variant in variant_map:
                variant_data.append({
                    "old": old_variant,
                    "new": new_variant,
                    "barcode": old_variant.barcode,
                    "ref": old_variant.default_code,
                    "old_qty": old_variant.qty_available,
                })

            self._copy_variant_values(variant_map)
            self._copy_boms(product, new_product, variant_map)
            self._log_old_identifiers(new_product, product, variant_data)
            for data in variant_data:
                self._transfer_stock(
                    data["old"], data["new"],
                    data["old_qty"], data["old_qty"] * self.conversion_factor,
                )
            self._archive_old_product(product)

            # Re-apply the Point of Sale flag LAST: automations or other
            # modules may switch it on when the new product is created.
            if "available_in_pos" in product._fields:
                new_product.write({"available_in_pos": pos_flag})

            cr.execute("RELEASE SAVEPOINT %s" % savepoint_name)
            return new_product
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT %s" % savepoint_name)
            # The ORM cache may still hold values written before the rollback.
            self.env.invalidate_all()
            raise UserError(_(
                "Migration failed for product '%s' and was rolled back.\n\nError: %s"
            ) % (product.display_name, exc))

    def _create_replacement_product(self, product):
        # copy() also copies the attribute lines (copy=True on
        # attribute_line_ids), so Odoo regenerates the variants on the copy.
        vals = {
            "name": product.name,
            "uom_id": self.new_uom_id.id,
            "barcode": False,
            "default_code": False,
        }
        # Odoo does not copy the Point of Sale flag (it falls back to the
        # default = ticked), so keep the old product's setting explicitly.
        if "available_in_pos" in product._fields:
            vals["available_in_pos"] = product.available_in_pos
        return product.copy(vals)

    # ------------------------------------------------------------------
    # Variant matching
    # ------------------------------------------------------------------
    def _map_variants(self, old_product, new_product):
        """Return a list of (old_variant, new_variant) pairs.

        Variants are matched on their attribute values (e.g. Grade 8-9+ /
        500g), not on their order. Variants that don't exist yet on the new
        template (dynamic attributes) are created. New variants that have no
        active counterpart on the old template are archived, so the new
        product has exactly the same active variants as the old one.
        """
        PTAV = self.env["product.template.attribute.value"].with_context(active_test=False)
        new_ptavs = PTAV.search([("product_tmpl_id", "=", new_product.id)])
        ptav_by_value = {ptav.product_attribute_value_id.id: ptav for ptav in new_ptavs}

        pairs = []
        for old_variant in old_product.product_variant_ids:
            combination = PTAV
            for old_ptav in old_variant.product_template_attribute_value_ids:
                new_ptav = ptav_by_value.get(old_ptav.product_attribute_value_id.id)
                if not new_ptav:
                    raise UserError(_(
                        "Could not find attribute value '%s' on the new product."
                    ) % old_ptav.display_name)
                combination |= new_ptav

            new_variant = new_product._get_variant_for_combination(combination)
            if not new_variant:
                new_variant = new_product._create_product_variant(combination)
            if not new_variant:
                raise UserError(_(
                    "Could not create the matching variant for '%s' on the new product."
                ) % old_variant.display_name)
            pairs.append((old_variant, new_variant))

        matched = self.env["product.product"].concat(*[new for _old, new in pairs])
        extra = new_product.product_variant_ids - matched
        if extra:
            extra.write({"active": False})
        return pairs

    def _copy_variant_values(self, variant_map):
        """Copy per-variant values that live on product.product or on the
        attribute values, and are not carried over by template.copy()."""
        for old_variant, new_variant in variant_map:
            new_variant.write({
                # Cost per NEW unit: 1 old unit = factor new units, so the
                # cost of one new unit is old cost / factor. This keeps the
                # stock value identical before and after migration.
                "standard_price": old_variant.standard_price / self.conversion_factor,
                "weight": old_variant.weight,
                "volume": old_variant.volume,
            })

            # Price extras ("+10 AED for Grade 8-9+") live on the template
            # attribute values; copy them so sales prices stay the same.
            for old_ptav in old_variant.product_template_attribute_value_ids:
                new_ptav = new_variant.product_template_attribute_value_ids.filtered(
                    lambda p: p.product_attribute_value_id == old_ptav.product_attribute_value_id
                )
                if new_ptav and new_ptav.price_extra != old_ptav.price_extra:
                    new_ptav.price_extra = old_ptav.price_extra

    # ------------------------------------------------------------------
    # Open sale orders check
    # ------------------------------------------------------------------
    def _get_open_sale_orders(self, product):
        """Confirmed sale order lines that still need delivery or invoicing.

        Odoo refuses to archive a Kit BoM while such lines exist, and for any
        product they would leave pending deliveries on the archived product.
        """
        lines = self.env["sale.order.line"].search([
            ("product_id", "in", product.product_variant_ids.ids),
            ("state", "=", "sale"),
            ("invoice_status", "in", ("no", "to invoice")),
        ])
        return lines.order_id

    # ------------------------------------------------------------------
    # Bills of Materials
    # ------------------------------------------------------------------
    def _copy_boms(self, old_product, new_product, variant_map):
        """Copy the old product's BoMs (incl. Kits) to the new product.

        product.template.copy() does not copy BoMs. The BoM quantity is
        converted to the new UoM, and variant-specific attribute values on
        lines/by-products/operations are remapped to the new template.
        """
        if "mrp.bom" not in self.env:
            return
        boms = self.env["mrp.bom"].search([("product_tmpl_id", "=", old_product.id)])
        if not boms:
            return

        variant_by_old = {old.id: new for old, new in variant_map}
        PTAV = self.env["product.template.attribute.value"].with_context(active_test=False)
        ptav_by_value = {
            ptav.product_attribute_value_id.id: ptav
            for ptav in PTAV.search([("product_tmpl_id", "=", new_product.id)])
        }

        def remap(ptavs):
            new_ids = [
                ptav_by_value[p.product_attribute_value_id.id].id
                for p in ptavs if p.product_attribute_value_id.id in ptav_by_value
            ]
            return [(6, 0, new_ids)]

        for bom in boms:
            new_variant = False
            if bom.product_id:
                new_variant = variant_by_old.get(bom.product_id.id)
                if not new_variant:
                    continue  # BoM for an archived variant — nothing to copy to

            # Copy on the OLD template first (so Odoo duplicates the lines,
            # by-products and operations with correct links), then move
            # everything to the new template in ONE write, so the
            # attribute-value constraint is only checked once it's consistent.
            new_bom = bom.copy({"code": bom.code})
            vals = {
                "product_tmpl_id": new_product.id,
                "product_id": new_variant.id if new_variant else False,
                "product_uom_id": self.new_uom_id.id,
                "product_qty": bom.product_qty * self.conversion_factor,
                "bom_line_ids": [
                    (1, line.id, {"bom_product_template_attribute_value_ids":
                                  remap(line.bom_product_template_attribute_value_ids)})
                    for line in new_bom.bom_line_ids
                ],
            }
            if "byproduct_ids" in new_bom._fields:
                vals["byproduct_ids"] = [
                    (1, bp.id, {"bom_product_template_attribute_value_ids":
                                remap(bp.bom_product_template_attribute_value_ids)})
                    for bp in new_bom.byproduct_ids
                ]
            if "operation_ids" in new_bom._fields:
                vals["operation_ids"] = [
                    (1, op.id, {"bom_product_template_attribute_value_ids":
                                remap(op.bom_product_template_attribute_value_ids)})
                    for op in new_bom.operation_ids
                ]
            new_bom.write(vals)

    # ------------------------------------------------------------------
    # Chatter logging
    # ------------------------------------------------------------------
    def _log_old_identifiers(self, new_product, old_product, variant_data):
        rows = Markup("").join(
            Markup("<li>%s → %s — Barcode: %s, Internal Ref: %s</li>") % (
                data["old"].display_name,
                data["new"].display_name,
                data["barcode"] or _("(none)"),
                data["ref"] or _("(none)"),
            )
            for data in variant_data
        )
        body = Markup(
            "<b>%s</b> %s (ID: %s)<ul>%s</ul><i>%s</i>"
        ) % (
            _("Migrated from product:"),
            old_product.display_name,
            old_product.id,
            rows,
            _("Set the barcode/internal reference on the new variants manually once confirmed."),
        )
        new_product.message_post(body=body)
        old_product.message_post(body=Markup(_(
            "This product was migrated to a new Unit of Measure. "
            "Replacement product: %s (ID: %s)"
        )) % (new_product.display_name, new_product.id))

    # ------------------------------------------------------------------
    # Stock transfer (per variant)
    # ------------------------------------------------------------------
    def _transfer_stock(self, old_variant, new_variant, old_qty, new_qty):
        """Transfer stock from one old variant to its new variant via proper
        stock.move records (through the Inventory Adjustment virtual
        location), so valuation layers/accounting entries are generated
        correctly. Handles both positive and negative on-hand quantities.
        """
        if old_qty == 0:
            return

        Move = self.env["stock.move"]
        Quant = self.env["stock.quant"]

        inventory_loc = self.env.ref("stock.location_inventory", raise_if_not_found=False)
        if not inventory_loc:
            inventory_loc = self.env["stock.location"].search(
                [("usage", "=", "inventory")], limit=1
            )
        if not inventory_loc:
            raise UserError(_(
                "Could not find an 'Inventory Adjustment' virtual location. "
                "Please check your Inventory app configuration."
            ))

        quants = Quant.search([
            ("product_id", "=", old_variant.id),
            ("location_id.usage", "=", "internal"),
            ("quantity", "!=", 0),
        ])
        total_old = sum(quants.mapped("quantity")) or old_qty

        old_uom = old_variant.uom_id.id
        new_uom = new_variant.uom_id.id

        for quant in quants:
            qty_signed = quant.quantity
            qty_in_signed = new_qty * (qty_signed / total_old) if total_old else 0.0
            location = quant.location_id

            if qty_signed > 0:
                self._do_move(Move, old_variant.id, old_uom,
                              abs(qty_signed), location.id, inventory_loc.id)
                if qty_in_signed > 0:
                    self._do_move(Move, new_variant.id, new_uom,
                                  abs(qty_in_signed), inventory_loc.id, location.id)
            else:
                self._do_move(Move, old_variant.id, old_uom,
                              abs(qty_signed), inventory_loc.id, location.id)
                if qty_in_signed < 0:
                    self._do_move(Move, new_variant.id, new_uom,
                                  abs(qty_in_signed), location.id, inventory_loc.id)

    def _do_move(self, Move, product_id, uom_id, qty, src_location_id, dest_location_id):
        move = Move.create({
            "product_id": product_id,
            "product_uom_qty": qty,
            "product_uom": uom_id,
            "location_id": src_location_id,
            "location_dest_id": dest_location_id,
        })
        move._action_confirm()
        move._action_assign()

        if not move.move_line_ids:
            self.env["stock.move.line"].create({
                "move_id": move.id,
                "product_id": product_id,
                "product_uom_id": uom_id,
                "location_id": src_location_id,
                "location_dest_id": dest_location_id,
                "quantity": qty,
            })
        else:
            move.move_line_ids.write({"quantity": qty})

        move.picked = True
        move._action_done()
        return move

    # ------------------------------------------------------------------
    # Archiving
    # ------------------------------------------------------------------
    def _archive_old_product(self, old_product):
        # Read the variants before archiving, otherwise active_test hides them.
        old_variants = old_product.with_context(active_test=False).product_variant_ids
        old_product.write({
            "active": False,
            "sale_ok": False,
            "purchase_ok": False,
            "barcode": False,
            "default_code": False,
        })
        # Barcodes/references live on each variant — clear all of them so
        # they can be reused on the new variants.
        if old_variants:
            old_variants.write({"barcode": False, "default_code": False})