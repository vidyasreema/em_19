/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

/**
 * Enforcement level set on the product form. Products that were never
 * configured, or a session opened before the module upgrade, fall back to
 * "none" so nothing is blocked by accident.
 */
export function getRawMaterialEnforcement(product) {
    return (
        product?.raw_material_enforcement ||
        product?.product_tmpl_id?.raw_material_enforcement ||
        "none"
    );
}

patch(PosOrder.prototype, {
    /**
     * Returns the order lines that are for a manufactured product but
     * have no raw materials attached yet.
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

    /**
     * Splits the lines missing raw materials by their own product's
     * enforcement level. Each line is judged on its product alone, so one
     * order can hold a blocked line, a warned line and an unchecked line
     * at the same time.
     */
    getRawMaterialViolations() {
        const result = { force: [], warning: [] };
        for (const line of this.getLinesMissingRawMaterials()) {
            const level = getRawMaterialEnforcement(line.product_id);
            if (level === "force" || level === "warning") {
                result[level].push(line);
            }
        }
        return result;
    },
});