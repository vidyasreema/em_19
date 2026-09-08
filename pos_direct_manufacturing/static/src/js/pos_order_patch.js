/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {
    /**
     * Returns the order lines that are for a manufactured product but
     * have no raw materials attached yet.
     *
     * Used together with the POS config's enforcement setting to decide
     * whether to block or warn at order confirmation.
     */
    getLinesMissingRawMaterials() {
        return this.lines.filter((line) => {
            // Refund lines carry a negative quantity and inherit the raw
            // materials of the original sale, so requiring them here would
            // make refunds of manufactured products impossible.
            if (line.qty <= 0 || line.refunded_orderline_id) {
                return false;
            }
            const product = line.product_id;
            const isManufactured = Boolean(product && product.is_manufacture_route);
            const hasRawMaterials = Boolean(
                line.raw_material_ids && line.raw_material_ids.length > 0
            );
            return isManufactured && !hasRawMaterials;
        });
    },
});