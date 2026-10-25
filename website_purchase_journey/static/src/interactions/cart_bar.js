import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

// "View cart · N items · total" at the bottom of the shop pages: refreshed
// after each Add / + / − of the product cards and the weight sheet. A cart
// without a delivery address opens the "Address details" sheet first.
export class JourneyCartBar extends Interaction {
    static selector = ".o_journey_cart_bar";
    dynamicContent = {
        _document: { "t-on-journey_cart_changed": this.refresh },
        _root: { "t-on-click": this.onClick },
    };

    onClick(ev) {
        if (this.el.dataset.needsAddress === "1" && document.querySelector(".o_journey_address_modal")) {
            ev.preventDefault();
            document.dispatchEvent(new CustomEvent("journey_open_address"));
        }
    }

    async refresh() {
        const { quantity, amount, needs_address } = await this.waitFor(rpc("/shop/journey/cart_total", {}));
        this.el.querySelector(".o_journey_cart_bar_qty").textContent = quantity;
        this.el.querySelector(".o_journey_cart_bar_items").textContent = quantity === 1 ? _t("item") : _t("items");
        this.el.querySelector(".o_journey_cart_bar_amount").textContent = amount;
        this.el.dataset.needsAddress = needs_address ? "1" : "0";
        this.el.classList.toggle("d-none", !quantity);
    }
}

registry.category("public.interactions").add("website_purchase_journey.cart_bar", JourneyCartBar);
