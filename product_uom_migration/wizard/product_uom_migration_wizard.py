# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
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

        new_products = self.env["product.template"]
        skipped = []
        failed = []

        for product in self.product_ids:
            if product.uom_id == self.new_uom_id:
                skipped.append(_("'%s' already uses this Unit of Measure.") % product.display_name)
                continue
            if product.product_variant_count > 1:
                skipped.append(_("'%s' has multiple variants — not supported yet.") % product.display_name)
                continue
            if product.qty_available < 0 and not self.allow_negative_stock:
                skipped.append(_(
                    "'%s' has negative stock (%.2f). Correct the stock first, or "
                    "check 'Allow Negative Stock Migration' to carry it over."
                ) % (product.display_name, product.qty_available))
                continue

            try:
                new_product = self._migrate_single_product(product)
                new_products |= new_product
            except UserError as e:
                failed.append(str(e))

        messages = []
        if skipped:
            messages.append(_("Skipped:\n%s") % "\n".join(skipped))
        if failed:
            messages.append(_("Failed:\n%s") % "\n".join(failed))

        if messages and new_products:
            new_products.message_post(body="\n\n".join(messages))
        elif messages and not new_products:
            raise UserError("\n\n".join(messages))

        if not new_products:
            raise UserError(_("No products were migrated."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Migrated Products"),
            "res_model": "product.template",
            "view_mode": "list,form",
            "domain": [("id", "in", new_products.ids)],
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
            old_variant = product.product_variant_ids[:1]
            old_barcode = old_variant.barcode or product.barcode
            old_ref = old_variant.default_code or product.default_code
            old_qty = product.qty_available
            new_qty = old_qty * self.conversion_factor

            new_product = self._create_replacement_product(product)
            self._log_old_identifiers(new_product, product, old_barcode, old_ref)
            self._transfer_stock(product, new_product, old_qty, new_qty)
            self._archive_old_product(product)

            cr.execute("RELEASE SAVEPOINT %s" % savepoint_name)
            return new_product
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT %s" % savepoint_name)
            raise UserError(_(
                "Migration failed for product '%s' and was rolled back.\n\nError: %s"
            ) % (product.display_name, exc))

    def _create_replacement_product(self, product):
        new_product = product.copy({
            "name": product.name,
            "uom_id": self.new_uom_id.id,
            "barcode": False,
            "default_code": False,
        })
        return new_product

    def _log_old_identifiers(self, new_product, old_product, old_barcode, old_ref):
        body = Markup(_(
            "<b>Migrated from product:</b> %(name)s (ID: %(id)s)<br/>"
            "<b>Old Barcode:</b> %(barcode)s<br/>"
            "<b>Old Internal Reference:</b> %(ref)s<br/>"
            "<i>Set the barcode/internal reference on this new product "
            "manually once confirmed.</i>"
        ) % {
            "name": old_product.display_name,
            "id": old_product.id,
            "barcode": old_barcode or _("(none)"),
            "ref": old_ref or _("(none)"),
        })
        new_product.message_post(body=body)
        old_product.message_post(
            body=Markup(_(
                "This product was migrated to a new Unit of Measure. "
                "Replacement product: %s (ID: %s)"
            ) % (new_product.display_name, new_product.id))
        )

    def _transfer_stock(self, old_product, new_product, old_qty, new_qty):
        """Transfer stock from the old product to the new one via proper
        stock.move records (through the Inventory Adjustment virtual
        location), so valuation layers/accounting entries are generated
        correctly. Handles both positive and negative on-hand quantities.
        """
        if old_qty == 0:
            return

        Move = self.env["stock.move"]
        Quant = self.env["stock.quant"]

        old_variant = old_product.product_variant_ids[:1]
        new_variant = new_product.product_variant_ids[:1]

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

        for quant in quants:
            qty_signed = quant.quantity
            qty_in_signed = new_qty * (qty_signed / total_old) if total_old else 0.0
            location = quant.location_id

            new_product.write({"standard_price": old_product.standard_price})

            if qty_signed > 0:
                # Normal case: positive stock leaves old, enters new.
                self._do_move(Move, old_variant.id, old_product.uom_id.id,
                               abs(qty_signed), location.id, inventory_loc.id)
                if qty_in_signed > 0:
                    self._do_move(Move, new_variant.id, new_product.uom_id.id,
                                   abs(qty_in_signed), inventory_loc.id, location.id)
            else:
                # Negative stock case: bring old product back to zero by
                # receiving the shortfall, then create the same shortfall
                # on the new product by sending stock out from it.
                self._do_move(Move, old_variant.id, old_product.uom_id.id,
                               abs(qty_signed), inventory_loc.id, location.id)
                if qty_in_signed < 0:
                    self._do_move(Move, new_variant.id, new_product.uom_id.id,
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
            # Nothing was available to reserve (e.g. taking stock out of a
            # product with 0 or negative on-hand). Create the move line
            # manually so the quantity actually gets applied instead of
            # silently doing nothing.
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

    def _archive_old_product(self, old_product):
        old_product.write({
            "active": False,
            "sale_ok": False,
            "purchase_ok": False,
        })