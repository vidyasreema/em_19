import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {
    setPricelist(pricelist) {
        super.setPricelist(pricelist);
        for (const line of this.lines) {
            if (line.pack_uom_id) {
                line.applyPackPrice();
            }
        }
    },
});