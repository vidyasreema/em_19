import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

patch(ProductScreen.prototype, {
    /**
     * Keypad ⌫ on a pack line in quantity mode removes one pack at a time
     * (3 cartons -> 2 -> 1). On the last pack, Odoo's normal ⌫ behaviour applies.
     */
    onNumpadClick(buttonValue) {
        const line = this.currentOrder?.getSelectedOrderline();
        const packCount = line?.getPackCount?.() || 0;
        if (buttonValue === "Backspace" && this.pos.numpadMode === "quantity" && packCount) {
            if (packCount > 1) {
                line.setQuantity(line.getQuantity() - line.getQtyPerPack());
                this.numberBuffer.reset();
                return;
            }
            this.numberBuffer.reset();
        }
        return super.onNumpadClick(buttonValue);
    },
});