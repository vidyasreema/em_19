/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { PaymentLinkInPopup } from "./payment_link_in_popup";

patch(Navbar.prototype, {
    setup() {
        super.setup(...arguments);
        this.pliDialog = useService("dialog");
        this.pliNotification = useService("notification");
    },

    async onClickPaymentLinkIn() {
        const payload = await makeAwaitable(this.pliDialog, PaymentLinkInPopup, {});
        if (!payload) {
            return;
        }
        try {
            await this.pos.data.call("pos.session", "try_payment_link_in", [
                [this.pos.session.id],
                payload.amount,
                payload.reason,
                false,
            ]);
            this.pliNotification.add(_t("Payment Link In recorded."), { type: "success" });
        } catch (error) {
            this.pliNotification.add(error.data?.message || error.message, { type: "danger" });
        }
    },
});