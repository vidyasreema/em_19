import { patch } from "@web/core/utils/patch";
import { ProductPricelist } from "@point_of_sale/app/models/product_pricelist";

patch(ProductPricelist.prototype, {
    findBestRule(rules, quantity, packUomId = false) {
        const filteredRules = [...rules].filter((rule) =>
            packUomId ? rule.pack_uom_id?.id === packUomId : !rule.pack_uom_id
        );
        return super.findBestRule(filteredRules, quantity);
    },
});