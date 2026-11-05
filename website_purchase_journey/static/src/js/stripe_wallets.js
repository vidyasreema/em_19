import { patch } from "@web/core/utils/patch";
import { PaymentForm } from "@payment/interactions/payment_form";

// Annex 3B, 4.4 and 4.5: in the Stripe card form, Apple Pay / Google Pay come first and
// are open by default where the device offers them; the manual card entry stays
// collapsed until it is tapped. Without a wallet the card entry is the only choice.
const PAYMENT_ELEMENT_OPTIONS = {
    layout: { type: "accordion", defaultCollapsed: false, radios: false, spacedAccordionItems: true },
    paymentMethodOrder: ["apple_pay", "google_pay", "card"],
};

/**
 * Stripe builds its card form with the global `Stripe` of js.stripe.com (loaded by
 * the payment form, before this runs): wrap it once so the payment element of the
 * order page gets the options above. Nothing changes if Stripe is not used.
 */
function journeyWrapStripe() {
    const OriginalStripe = window.Stripe;
    if (!OriginalStripe || OriginalStripe.journeyWrapped || !document.querySelector(".o_journey_order")) {
        return;
    }
    const wrapped = function (...args) {
        const stripe = OriginalStripe(...args);
        const elements = stripe.elements.bind(stripe);
        stripe.elements = (options) => {
            const group = elements(options);
            const create = group.create.bind(group);
            group.create = (type, elementOptions) =>
                create(type, type === "payment" ? { ...PAYMENT_ELEMENT_OPTIONS, ...elementOptions } : elementOptions);
            return group;
        };
        return stripe;
    };
    wrapped.journeyWrapped = true;
    window.Stripe = wrapped;
}

patch(PaymentForm.prototype, {
    setup() {
        super.setup();
        journeyWrapStripe();
    },
});
