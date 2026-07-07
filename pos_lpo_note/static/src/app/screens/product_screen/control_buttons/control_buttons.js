import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { TextInputPopup } from "@point_of_sale/app/components/popups/text_input_popup/text_input_popup";

patch(ControlButtons.prototype, {
    onClickLpo() {
        const order = this.pos.getOrder();
        this.dialog.add(TextInputPopup, {
            title: _t("LPO Number"),
            placeholder: _t("Enter customer's LPO / PO number"),
            startingValue: order.lpo_number || "",
            getPayload: (lpoNumber) => {
                order.lpo_number = lpoNumber.trim();
            },
        });
    },
    onClickClearLpo() {
        const order = this.pos.getOrder();
        order.lpo_number = "";
    },
});
