/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { RawMaterialPopup } from "@pos_direct_manufacturing/js/raw_material_popup";

patch(Orderline.prototype, {
    setup() {
        super.setup(...arguments);
        this.dialog = useService("dialog");
        this.pos = usePos();
    },

    get showRawMaterialButton() {
        if (this.props.mode !== "display") {
            return false;
        }
        const line = this.line;
        const order = line.order_id;

        // The ticket screen renders this same component for past orders so
        // the cashier can pick refund quantities. Those orders are already
        // synced and paid: their raw materials are a historical record and
        // editing them changes nothing on the server.
        if (order?.finalized) {
            return false;
        }

        // Refund lines carry a negative quantity and their raw materials
        // are never read: the server skips Manufacturing Order creation
        // for them, and the refund reverses the original sale's MO
        // instead.
        if (line.qty <= 0 || line.refunded_orderline_id) {
            return false;
        }

        const product = line.product_id;
        return Boolean(product && product.is_manufacture_route);
    },

    onClickRawMaterial(ev) {
        ev.stopPropagation();
        const line = this.line;

        const existingMaterials = [];
        for (const m of line.raw_material_ids || []) {
            // A raw material saved before the product-loading fix can have
            // an empty product_id: the id it was created with had no record
            // behind it in the session. Reading m.product_id.id on those
            // threw a TypeError and the popup would not open at all.
            if (!m.product_id) {
                console.warn(
                    "[pos_direct_manufacturing] raw material %s has no product " +
                        "loaded in this session and cannot be shown.",
                    m.id
                );
                continue;
            }
            existingMaterials.push({
                productId: m.product_id.id,
                productName: m.product_id.display_name,
                qty: m.qty,
                // uom_id is a related field filled in server-side, so records
                // created earlier in this session do not have it yet. Fall back
                // to the product's own unit, otherwise the popup treats the
                // line as "unit unknown" and skips the quantity check on every
                // reopen.
                uomId:
                    m.uom_id?.id ||
                    m.product_id?.uom_id?.id ||
                    m.product_id?.product_tmpl_id?.uom_id?.id ||
                    null,
            });
        }

        this.dialog.add(RawMaterialPopup, {
            existingMaterials,
            productQty: line.qty,
            // The finished product's unit: the popup converts raw material
            // quantities into this before comparing totals.
            productUomId:
                line.product_id?.uom_id?.id ||
                line.product_id?.product_tmpl_id?.uom_id?.id ||
                null,
            getPayload: (materialLines) => {
                this.saveRawMaterials(materialLines);
            },
        });
    },

    saveRawMaterials(materialLines) {
        const line = this.line;
        const productModel = this.pos.models["product.product"];

        // The popup already loads each chosen product into the session, so
        // this should never fire. It stays as a last line of defence: a raw
        // material written against an id with no record behind it produces
        // product_id = NULL, which the database rejects — and it rejects it
        // at sync time, on the payment screen, with the customer waiting.
        // Failing here instead keeps the damage inside the popup.
        const unresolved = materialLines.filter(
            (m) => !m.productId || !productModel.get(m.productId)
        );
        if (unresolved.length > 0) {
            this.dialog.add(AlertDialog, {
                title: "Raw material not available",
                body:
                    "These raw materials could not be loaded in this session " +
                    "and were not saved: " +
                    unresolved.map((m) => m.productName || `#${m.productId}`).join(", "),
            });
            return;
        }

        const existingLines = line.raw_material_ids || [];
        for (const existing of [...existingLines]) {
            existing.delete();
        }
        for (const material of materialLines) {
            this.pos.models["pos.order.line.raw.material"].create({
                order_line_id: line,
                // Pass the record itself rather than the bare id. An id the
                // store cannot resolve silently becomes NULL; a record
                // cannot.
                product_id: productModel.get(material.productId),
                qty: material.qty,
            });
        }
    },
});