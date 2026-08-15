/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { DataServiceOptions } from "@point_of_sale/app/models/data_service_options";

patch(DataServiceOptions.prototype, {
    get dynamicModels() {
        return [...super.dynamicModels, "pos.order.line.raw.material"];
    },

    get cascadeDeleteModels() {
        return [...super.cascadeDeleteModels, "pos.order.line.raw.material"];
    },
});