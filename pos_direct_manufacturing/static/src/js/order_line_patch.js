/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
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
        const product = this.line.product_id;
        return Boolean(product && product.is_manufacture_route);
    },

    onClickRawMaterial(ev) {
        ev.stopPropagation();
        const line = this.line;
        const existingMaterials = (line.raw_material_ids || []).map((m) => ({
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
        }));
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
        const existingLines = line.raw_material_ids || [];
        for (const existing of [...existingLines]) {
            existing.delete();
        }
        for (const material of materialLines) {
            this.pos.models["pos.order.line.raw.material"].create({
                order_line_id: line,
                product_id: material.productId,
                qty: material.qty,
            });
        }
    },
});