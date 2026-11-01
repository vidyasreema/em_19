import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// Order again (Annex 3 C7): the products of a past order go in the cart
// (out-of-stock products are skipped), then the order page opens. When the
// cart already has products, the customer chooses: replace them or add.
export class JourneyReorder extends Interaction {
    static selector = ".o_journey_reorder";
    dynamicContent = {
        _root: { "t-on-click": this.locked(() => this.reorder("ask"), true) },
    };

    async reorder(mode) {
        const { orderId, accessToken } = this.el.dataset;
        let result;
        try {
            result = await this.waitFor(rpc("/shop/order/reorder", {
                order_id: parseInt(orderId),
                access_token: accessToken || null,
                mode,
            }));
        } catch {
            result = { error: _t("These products cannot be ordered again.") };
        }
        if (result.ask) {
            this.services.dialog.add(ConfirmationDialog, {
                title: _t("Your cart already has products"),
                body: _t("Replace them with the products of this order, or add these products to your cart?"),
                confirmLabel: _t("Replace with this order"),
                confirm: () => this.reorder("replace"),
                cancelLabel: _t("Add to my cart"),
                cancel: () => this.reorder("add"),
                dismiss: () => {},
            });
            return;
        }
        if (result.error) {
            this.services.notification.add(result.error, { type: "warning" });
            return;
        }
        try {
            window.sessionStorage.setItem("website_sale_cart_quantity", result.cart_quantity);
        } catch {
            // Storage blocked: the cart icon updates on the next page
        }
        window.location.href = "/shop/order";
    }
}

registry.category("public.interactions").add("website_purchase_journey.reorder", JourneyReorder);
