import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);
        if (this.lpo_number === undefined) {
            this.lpo_number = vals?.lpo_number || "";
        }
    },
});