/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";

export class PaymentLinkInPopup extends Component {
    static template = "pos_payment_link_in.PaymentLinkInPopup";
    static components = { Dialog };
    static props = {
        getPayload: Function,
        close: Function,
    };

    setup() {
        this.state = useState({ amount: "", reason: "", error: "" });
    }

    confirm() {
        const amount = parseFloat(this.state.amount);
        if (!amount || amount <= 0) {
            this.state.error = _t("The amount must be greater than zero.");
            return;
        }
        if (!this.state.reason.trim()) {
            this.state.error = _t("A note is required.");
            return;
        }
        this.props.getPayload({ amount: amount, reason: this.state.reason.trim() });
        this.props.close();
    }
}