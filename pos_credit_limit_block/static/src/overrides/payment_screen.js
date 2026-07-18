/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

/**
 * Returns the order total, coping with the camelCase rename that
 * happened across recent Odoo versions.
 */
function getOrderTotal(order) {
    if (typeof order.getTotalWithTax === "function") {
        return order.getTotalWithTax();
    }
    if (typeof order.get_total_with_tax === "function") {
        return order.get_total_with_tax();
    }
    return 0;
}

function getOrderPartner(order) {
    if (typeof order.getPartner === "function") {
        return order.getPartner();
    }
    if (typeof order.get_partner === "function") {
        return order.get_partner();
    }
    return order.partner_id || null;
}

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        if (paymentMethod.type === "pay_later") {
            const order = this.currentOrder;

            // Skip refunds (negative total) — they lower the debt.
            if (getOrderTotal(order) >= 0) {
                const partner = getOrderPartner(order);
                if (partner) {
                    const status = await this.env.services.orm.call(
                        "res.partner",
                        "get_pos_credit_status",
                        [partner.id]
                    );
                    if (status.blocked) {
                        this.dialog.add(AlertDialog, {
                            title: _t("Credit Limit Exceeded"),
                            body: status.message,
                        });
                        return false;
                    }
                }
            }
        }
        return super.addNewPaymentLine(...arguments);
    },
});