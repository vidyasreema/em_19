/** @odoo-module **/

/**
 * Raw material quantity check, shared by the raw material popup and the
 * payment button so both judge a line the same way.
 */

/**
 * Two units can be compared only when they share a reference unit.
 * Odoo 19 keeps units in a tree and stores the path on each record, so
 * a shared root is what makes a conversion possible. kg and g convert;
 * kg and Units do not.
 */
function uomsAreComparable(uomA, uomB) {
    if (!uomA || !uomB || !uomA.parent_path || !uomB.parent_path) {
        return false;
    }
    return uomA.parent_path.split("/")[0] === uomB.parent_path.split("/")[0];
}

function roundQty(value) {
    return Math.round(value * 1000) / 1000;
}

/**
 * Total of the raw material quantities ({ qty, uomId } each) expressed in
 * the finished product's unit. Returns null when the comparison does not
 * apply — no unit on the finished product, or a material whose unit
 * cannot be converted into it (kg of meat for a product sold in Units).
 */
export function getConvertedRawMaterialTotal(uomModel, materials, productUomId) {
    if (!uomModel || !productUomId) {
        return null;
    }
    const targetUom = uomModel.get(productUomId);
    if (!targetUom || !targetUom.factor) {
        return null;
    }

    let total = 0;
    for (const material of materials) {
        const lineUom = material.uomId && uomModel.get(material.uomId);
        if (!lineUom || !uomsAreComparable(lineUom, targetUom)) {
            return null;
        }
        // Same formula as UomUom._compute_quantity on the server.
        total += (material.qty * lineUom.factor) / targetUom.factor;
    }
    return roundQty(total);
}

/**
 * Compares the raw material total with the quantity sold.
 *
 * - "over":  more than the sold quantity plus the tolerance. Blocked: the
 *            Manufacturing Order would pull more stock than it produces.
 * - "under": less than the sold quantity minus the tolerance. The cashier
 *            is warned and may continue (trim, bone or cooking loss).
 * - null:    within the tolerance, or the units are not convertible.
 */
export function compareRawMaterialTotal(total, productQty, tolerance) {
    if (total === null || !productQty) {
        return null;
    }
    if (total > roundQty(productQty + tolerance)) {
        return "over";
    }
    if (total < roundQty(productQty - tolerance)) {
        return "under";
    }
    return null;
}
