/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";

patch(Orderline.prototype, {
    get lineScreenValues() {
        const vals = { ...super.lineScreenValues };
        const line = this.props.line;
        if (!line.order_id) {
            return vals;
        }
        try {
            const qty       = line.qty ?? 0;
            const unitPrice = line.price_unit ?? 0;
            const symbol    = line.currency?.symbol ?? '';
            const unit      = line.product_id?.uom_id?.name ?? '';

            const qtyStr   = parseFloat(qty).toFixed(2);
            const priceStr = parseFloat(unitPrice).toFixed(2);

            if (line.price !== 0) {
                vals.displayPriceUnit = unit
                    ? `${qtyStr} x ${priceStr} ${symbol} / ${unit}`
                    : `${qtyStr} x ${priceStr} ${symbol}`;
            }
        } catch (_e) {}
        return vals;
    },
});