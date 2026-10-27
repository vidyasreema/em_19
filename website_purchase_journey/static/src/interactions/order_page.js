import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

// The promise is checked again every minute (e.g. 19:00 passes while the page is open).
const PROMISE_CHECK_MS = 60000;
const SUMMARY_MARGIN = 32;
// Promise shown before the page reloaded itself (null when the customer opened it)
const RELOAD_PROMISE_KEY = "journey_reload_promise";
// Parts of the page with amounts, taken again from the server after a cart change
const REFRESHED_PARTS = [
    ".o_journey_savebar_wrap",
    ".o_journey_sumtog_total",
    "#o_journey_summary",
    ".o_journey_mycoupons_list",
    ".o_journey_payment",
    ".o_journey_dock",
];

function popReloadPromise() {
    try {
        const message = sessionStorage.getItem(RELOAD_PROMISE_KEY);
        sessionStorage.removeItem(RELOAD_PROMISE_KEY);
        return message;
    } catch {
        return null;
    }
}

/**
 * Single order page. A change of the cart (quantity, coupon) takes the parts
 * with amounts (summary, payment form, order button) from the server again,
 * without reloading the page: the summary stays open, the form keeps what was
 * typed and the payment form always has the amount of the order. A change of
 * address reloads the page.
 */
export class JourneyOrderPage extends Interaction {
    static selector = ".o_journey_order";
    dynamicContent = {
        ".o_journey_line_plus": { "t-on-click": this.locked((ev) => this.changeLine(ev, 1), true) },
        ".o_journey_line_minus": { "t-on-click": this.locked((ev) => this.changeLine(ev, -1), true) },
        ".o_journey_coupon_apply": { "t-on-click": this.locked(this.applyCoupon, true) },
        ".o_journey_coupon_code": { "t-on-keydown": this.onCouponKeydown },
        ".o_journey_coupon_remove": { "t-on-click": this.locked(this.removeCoupon, true) },
        ".o_journey_guest_go": { "t-on-click": () => this.setGuest(true) },
        ".o_journey_show_signup": { "t-on-click": () => this.setGuest(false) },
        ".o_journey_chip": { "t-on-click": this.toggleChip },
        ".o_journey_email": { "t-on-input": this.clearEmailError },
        ".o_journey_address_pick": { "t-on-change": this.locked(this.pickAddress, true) },
        ".o_journey_sumtog": { "t-on-click": this.onSummaryToggle },
        ".o_journey_mycoupon_copy": { "t-on-click": this.copyCoupon },
        ".o_journey_mycoupon_apply": { "t-on-click": this.locked(this.applyMyCoupon, true) },
    };

    setup() {
        this.promiseModalEl = this.el.querySelector(".o_journey_promise_modal");
        this.promiseModal = window.Modal.getOrCreateInstance(this.promiseModalEl);
        this.registerCleanup(() => this.promiseModal.dispose());
        // Before the payment starts: save and check the form (capture phase,
        // so it runs before the payment form of Odoo).
        this.onPlaceClick = (ev) => this.beforePayment(ev);
        document.addEventListener("click", this.onPlaceClick, true);
        this.registerCleanup(() => document.removeEventListener("click", this.onPlaceClick, true));
        this.onResize = () => this.updateSticky();
        window.addEventListener("resize", this.onResize);
        this.registerCleanup(() => window.removeEventListener("resize", this.onResize));
    }

    start() {
        this.updateSticky();
        // Each time the page is opened; after its own reloads (cart changes...)
        // only when the promise changed (e.g. another address)
        const shownBefore = popReloadPromise();
        if (this.el.dataset.showPromisePopup === "1" && shownBefore !== this.el.dataset.promiseMessage) {
            this.promiseModal.show();
        }
        if (this.el.dataset.promiseMessage) {
            this.waitForTimeout(() => this.checkPromise(), PROMISE_CHECK_MS);
        }
    }

    reload() {
        try {
            sessionStorage.setItem(RELOAD_PROMISE_KEY, this.el.dataset.promiseMessage || "");
        } catch {
            // Storage blocked: the popup just opens again after the reload
        }
        window.location.reload();
    }

    /** Cart changed: the parts with amounts again, the page stays where it is. */
    async refresh() {
        let doc;
        try {
            const response = await this.waitFor(fetch(window.location.pathname));
            doc = new DOMParser().parseFromString(await this.waitFor(response.text()), "text/html");
        } catch {
            this.reload();
            return;
        }
        const newPage = doc.querySelector(".o_journey_order");
        const pairs = REFRESHED_PARTS.map((sel) => [this.el.querySelector(sel), newPage?.querySelector(sel)]);
        if (!newPage || pairs.some(([oldEl, newEl]) => !oldEl !== !newEl)) {
            this.reload(); // e.g. the cart is empty now
            return;
        }
        // All the parts first, then their interactions: the payment form of Odoo
        // must start with the new order button already in the page
        const interactions = this.services["public.interactions"];
        const replaced = pairs.filter(([oldEl]) => oldEl);
        for (const [oldEl, newEl] of replaced) {
            interactions.stopInteractions(oldEl);
            // Same element, new content: the summary stays open or closed (phones)
            oldEl.replaceChildren(...newEl.childNodes);
        }
        for (const [oldEl] of replaced) {
            interactions.startInteractions(oldEl);
        }
        // Cart icon of the header
        const quantity = doc.querySelector(".my_cart_quantity")?.textContent.trim();
        if (quantity) {
            for (const el of document.querySelectorAll(".my_cart_quantity")) {
                el.textContent = quantity;
            }
            try {
                sessionStorage.setItem("website_sale_cart_quantity", quantity);
            } catch {
                // Storage blocked: the icon is right on the next page
            }
        }
        this.updateContent();
        this.updateSticky();
    }

    // ── Cart ──────────────────────────────────────────────────────────────

    async changeLine(ev, delta) {
        const line = ev.currentTarget.closest(".o_journey_cart_line");
        const quantity = Math.max((parseFloat(line.dataset.qty) || 0) + delta, 0);
        await this.waitFor(rpc("/shop/cart/update", { line_id: parseInt(line.dataset.lineId), quantity }));
        await this.refresh();
    }

    onCouponKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.applyCoupon();
        }
    }

    async applyCoupon() {
        const code = this.el.querySelector(".o_journey_coupon_code").value.trim();
        if (!code) {
            return;
        }
        await this.waitFor(rpc("/shop/order/coupon", { code }));
        await this.refresh();
        // Wrong code: it stays in the field, under the message
        const input = this.el.querySelector(".o_journey_coupon_code");
        if (input && this.el.querySelector(".o_journey_coupon_error")) {
            input.value = code;
        }
    }

    async removeCoupon(ev) {
        await this.waitFor(rpc("/shop/order/coupon/remove", { line_id: parseInt(ev.currentTarget.dataset.lineId) }));
        await this.refresh();
    }

    // ── My coupons popup ─────────────────────────────────────────────────

    async copyCoupon(ev) {
        const button = ev.currentTarget;
        try {
            await this.waitFor(navigator.clipboard.writeText(button.dataset.code));
            button.textContent = _t("Copied");
        } catch {
            // No clipboard (old browser, http): the code stays visible to copy by hand
        }
    }

    async applyMyCoupon(ev) {
        const modalEl = this.el.querySelector(".o_journey_mycoupons_modal");
        await this.waitFor(rpc("/shop/order/coupon", { code: ev.currentTarget.dataset.code }));
        window.Modal.getOrCreateInstance(modalEl).hide();
        await this.refresh();
        this.el.querySelector(".o_journey_coupon")?.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    // ── Sign-up box / guest ──────────────────────────────────────────────

    setGuest(guest) {
        this.el.querySelector(".o_journey_gbox")?.classList.toggle("d-none", guest);
        this.el.querySelector(".o_journey_gline")?.classList.toggle("d-none", !guest);
        if (!guest) {
            this.el.querySelector(".o_journey_gbox")?.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        rpc("/shop/order/guest", { guest });
    }

    // ── Driver instructions, address ─────────────────────────────────────

    toggleChip(ev) {
        const chip = ev.currentTarget;
        chip.setAttribute("aria-pressed", chip.getAttribute("aria-pressed") === "true" ? "false" : "true");
    }

    async pickAddress(ev) {
        await this.waitFor(rpc("/shop/update_address", { partner_id: parseInt(ev.currentTarget.value), address_type: "delivery" }));
        this.reload();
    }

    // ── Summary ──────────────────────────────────────────────────────────

    onSummaryToggle(ev) {
        const button = ev.currentTarget;
        // Bootstrap toggles `collapsed` on the button after the click
        setTimeout(() => {
            button.querySelector(".o_journey_sumtog_label").textContent = button.classList.contains("collapsed")
                ? _t("Show order summary")
                : _t("Hide order summary");
        });
    }

    /** Pinned when it fits on the screen; scrolls normally when it is longer. */
    updateSticky() {
        const summary = this.el.querySelector(".o_journey_summary");
        if (summary) {
            // Header kept at the top ("Fixed" scroll effect): pinned under it
            const header = document.querySelector("header#top.o_header_fixed");
            const headerHeight = header ? header.offsetHeight : 0;
            summary.style.top = header ? `${headerHeight + 16}px` : "";
            summary.classList.toggle("o_journey_sticky", summary.offsetHeight + SUMMARY_MARGIN + headerHeight < window.innerHeight);
        }
    }

    // ── Promise ──────────────────────────────────────────────────────────

    async checkPromise() {
        const result = await this.waitFor(rpc("/shop/delivery/timing", {}));
        const message = result?.message || "";
        if (message && message !== this.el.dataset.promiseMessage) {
            this.el.dataset.promiseMessage = message;
            for (const el of this.el.querySelectorAll(".o_journey_promise_text")) {
                el.textContent = message;
            }
            for (const el of this.el.querySelectorAll(".o_journey_promise_date")) {
                el.textContent = result.date_label || "";
            }
            this.promiseModalEl.querySelector(".o_journey_promise_modal_text").textContent = message;
            this.promiseModal.show();
        }
        this.waitForTimeout(() => this.checkPromise(), PROMISE_CHECK_MS);
    }

    // ── Before the payment ───────────────────────────────────────────────

    showError(message, field) {
        this.errorField = field;
        const error = this.el.querySelector(".o_journey_form_error");
        error.textContent = message;
        error.classList.remove("d-none");
        const email = this.el.querySelector(".o_journey_email");
        email?.classList.toggle("is-invalid", field === "email");
        this.el.querySelector(".o_journey_address_error").classList.toggle("d-none", field !== "address");
        const target = field === "email" ? email : field === "address" ? this.el.querySelector("#o_journey_address") : error;
        target?.scrollIntoView({ behavior: "smooth", block: "center" });
        if (field === "email") {
            email.focus();
        }
    }

    /** The email is being changed (typed or filled in by the browser): its error goes away. */
    clearEmailError() {
        this.el.querySelector(".o_journey_email")?.classList.remove("is-invalid");
        if (this.errorField === "email") {
            this.el.querySelector(".o_journey_form_error").classList.add("d-none");
            this.errorField = null;
        }
    }

    async beforePayment(ev) {
        const button = ev.target.closest('button[name="o_payment_submit_button"]');
        if (!button || !this.el.contains(button) || this.validated) {
            return;
        }
        ev.preventDefault();
        ev.stopImmediatePropagation();
        const pressed = (key) => this.el.querySelector(`.o_journey_chip[data-key="${key}"]`)?.getAttribute("aria-pressed") === "true";
        const result = await this.waitFor(rpc("/shop/order/prepare", {
            email: this.el.querySelector(".o_journey_email")?.value || "",
            // Not shown to returning customers: null keeps their choice
            consent: this.el.querySelector(".o_journey_consent")?.checked ?? null,
            call_on_arrival: pressed("call_on_arrival"),
            note: this.el.querySelector(".o_journey_note")?.value || "",
            save_note: this.el.querySelector(".o_journey_save_note")?.checked || false,
        }));
        if (result.reload) {
            this.reload();
            return;
        }
        if (result.error) {
            this.showError(result.error, result.field);
            return;
        }
        this.el.querySelector(".o_journey_form_error").classList.add("d-none");
        // Hand over to the payment form of Odoo
        this.validated = true;
        try {
            button.click();
        } finally {
            this.validated = false;
        }
    }
}

registry.category("public.interactions").add("website_purchase_journey.order_page", JourneyOrderPage);
