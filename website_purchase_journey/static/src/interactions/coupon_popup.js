import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { throwConfetti } from "@website_purchase_journey/js/confetti";

async function copyCode(interaction, button) {
    try {
        await interaction.waitFor(navigator.clipboard.writeText(button.dataset.code));
        button.textContent = _t("Copied");
    } catch {
        // No clipboard (old browser, http): the code stays visible to copy by hand
    }
}

// Confirmation page: "Congratulations, you earned a coupon for your next
// order" opens once per order (not again when the page reloads, e.g. after
// "How did you hear about us?"), with a burst of confetti. The green box of
// the page stays.
export class JourneyCouponPopup extends Interaction {
    static selector = ".o_journey_coupon_modal";
    dynamicContent = {
        ".o_journey_coupon_copy": { "t-on-click": (ev) => copyCode(this, ev.currentTarget) },
    };

    start() {
        const key = `journey_coupon_popup_${this.el.dataset.orderId}`;
        try {
            if (window.localStorage.getItem(key)) {
                return;
            }
            window.localStorage.setItem(key, "1");
        } catch {
            // Storage blocked: the popup opens on each visit of the page
        }
        this.modal = window.Modal.getOrCreateInstance(this.el);
        this.registerCleanup(() => this.modal.dispose());
        this.modal.show();
        this.registerCleanup(throwConfetti());
    }
}

// My coupons: "You have a new coupon" with confetti, once per coupon. The
// server remembers it, so it is not shown again on another phone or browser.
export class JourneyNewCouponPopup extends Interaction {
    static selector = ".o_journey_newcoupon_modal";
    dynamicContent = {
        ".o_journey_coupon_copy": { "t-on-click": (ev) => copyCode(this, ev.currentTarget) },
    };

    start() {
        this.modal = window.Modal.getOrCreateInstance(this.el);
        this.registerCleanup(() => this.modal.dispose());
        this.modal.show();
        this.registerCleanup(throwConfetti());
        rpc("/my/coupons/celebrated", { card_ids: JSON.parse(this.el.dataset.cardIds) });
    }
}

registry
    .category("public.interactions")
    .add("website_purchase_journey.coupon_popup", JourneyCouponPopup)
    .add("website_purchase_journey.new_coupon_popup", JourneyNewCouponPopup);
