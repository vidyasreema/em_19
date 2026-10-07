/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { _t } from "@web/core/l10n/translation";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

/** One entry per product, even if it appears on several lines. */
function describeProducts(lines) {
    const names = new Set(lines.map((line) => line.product_id.display_name));
    return [...names].map((name) => `• ${name}`).join("\n");
}

patch(PosStore.prototype, {
    async pay() {
        const order = this.getOrder();
        const { force, warning } = order.getRawMaterialViolations();

        // Blocking takes priority: if any line is Mandatory, stop here.
        // Warning lines are raised on the next attempt, once the
        // mandatory ones have their materials.
        if (force.length > 0) {
            await this.env.services.dialog.add(AlertDialog, {
                title: _t("Raw Materials Required"),
                body: _t(
                    "Payment cannot continue. The following product(s) require raw materials:\n%s\n\nTap \"+ Raw Material\" on each of these order lines, select the materials used, then try again.",
                    describeProducts(force)
                ),
            });
            return;
        }

        if (warning.length > 0) {
            const confirmed = await ask(this.env.services.dialog, {
                title: _t("Raw Materials Not Specified"),
                body: _t(
                    "No raw materials were selected for:\n%s\n\nIt is recommended to add them with \"+ Raw Material\" on the order line. Continue to payment anyway?",
                    describeProducts(warning)
                ),
            });
            if (!confirmed) {
                return;
            }
        }

        return super.pay(...arguments);
    },
});