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

/** "• Burger: 0.8 kg of raw materials for 1 kg sold", one per line. */
function describeQtyMismatches(mismatches) {
    return mismatches
        .map(({ line, total, uomName }) =>
            _t("• %(product)s: %(total)s of raw materials for %(qty)s sold", {
                product: line.product_id.display_name,
                total: `${total} ${uomName}`.trim(),
                qty: `${line.qty} ${uomName}`.trim(),
            })
        )
        .join("\n");
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

        // The popup checks the total when the materials are saved, but the
        // line quantity can still change afterwards.
        const { over, underMandatory, under } = order.getRawMaterialQtyMismatches();
        if (over.length > 0) {
            await this.env.services.dialog.add(AlertDialog, {
                title: _t("Too Much Raw Material"),
                body: _t(
                    "Payment cannot continue. The raw materials are more than the quantity sold:\n%s\n\nTap \"+ Raw Material\" on these order lines and correct the quantities, then try again.",
                    describeQtyMismatches(over)
                ),
            });
            return;
        }
        if (underMandatory.length > 0) {
            await this.env.services.dialog.add(AlertDialog, {
                title: _t("Raw Material Quantity Too Low"),
                body: _t(
                    "Payment cannot continue. These product(s) require the raw materials to add up to the quantity sold:\n%s\n\nTap \"+ Raw Material\" on these order lines and correct the quantities, then try again.",
                    describeQtyMismatches(underMandatory)
                ),
            });
            return;
        }
        if (under.length > 0) {
            const confirmed = await ask(this.env.services.dialog, {
                title: _t("Raw Material Quantity Too Low"),
                body: _t(
                    "The raw materials are less than the quantity sold:\n%s\n\nThey should add up to the quantity sold. Continue to payment anyway?",
                    describeQtyMismatches(under)
                ),
            });
            if (!confirmed) {
                return;
            }
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