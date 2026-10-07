import { patch } from "@web/core/utils/patch";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";

patch(OrderSummary.prototype, {
    /**
     * Keypad in quantity mode on a pack line: the typed number is the number of packs.
     * e.g. carton line, Qty -> 100 = 100 cartons (900 kg). Loose lines are unchanged.
     */
    _setValue(val) {
        const line = this.currentOrder?.getSelectedOrderline();
        const qtyPerPack = line?.getQtyPerPack?.() || 0;
        if (this.pos.numpadMode === "quantity" && line?.pack_uom_id && qtyPerPack && val !== "remove") {
            const packs = parseFloat(val);
            if (!isNaN(packs)) {
                return super._setValue(String(packs * qtyPerPack));
            }
        }
        return super._setValue(val);
    },
});