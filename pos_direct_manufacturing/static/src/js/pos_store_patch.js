/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { _t } from "@web/core/l10n/translation";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(PosStore.prototype, {
    async pay() {
        const order = this.getOrder();
        const enforcement = this.config.raw_material_enforcement;
        const missingLines = order.getLinesMissingRawMaterials();

        if (missingLines.length > 0 && enforcement !== "none") {
            const productNames = missingLines
                .map((line) => line.product_id.display_name)
                .join(", ");

            if (enforcement === "force") {
                await this.env.services.dialog.add(AlertDialog, {
                    title: _t("Raw Materials Required"),
                    body: _t(
                        "Please select raw materials before completing the order for: %s",
                        productNames
                    ),
                });
                return;
            }

            if (enforcement === "warning") {
                const confirmed = await ask(this.env.services.dialog, {
                    title: _t("Raw Materials Not Specified"),
                    body: _t(
                        "No raw materials were selected for: %s. Continue anyway?",
                        productNames
                    ),
                });
                if (!confirmed) {
                    return;
                }
            }
        }

        return super.pay(...arguments);
    },
});