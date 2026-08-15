/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {
    /**
     * Returns the order lines that are for a manufactured product but
     * have no raw materials attached yet.
     *
     * Detection only, for now — nothing reads or acts on this yet.
     * Step 3 will use this list, together with the enforcement setting,
     * to decide whether to block or warn at order confirmation.
     */
    getLinesMissingRawMaterials() {
        return this.lines.filter((line) => {
            const product = line.product_id;
            const isManufactured = Boolean(product && product.is_manufacture_route);
            const hasRawMaterials = Boolean(
                line.raw_material_ids && line.raw_material_ids.length > 0
            );
            return isManufactured && !hasRawMaterials;
        });
    },
});