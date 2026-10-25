import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

/** Cart quantity of the header (like the cart service of Odoo does after adding). */
function updateCartIcon(cartQuantity) {
    try {
        window.sessionStorage.setItem("website_sale_cart_quantity", cartQuantity);
    } catch {
        // storage blocked: only the page is updated
    }
    for (const el of document.querySelectorAll(".my_cart_quantity")) {
        el.textContent = cartQuantity;
        el.classList.toggle("d-none", !cartQuantity);
    }
    if (cartQuantity) {
        document.querySelector("li.o_wsale_my_cart")?.classList.remove("d-none");
    }
    // The "View cart" button refreshes its total
    document.dispatchEvent(new CustomEvent("journey_cart_changed"));
}

/**
 * Add or remove one unit of a product. The standard cart routes are called
 * directly (not the cart service) so that no "added to cart" popup piles up;
 * the card and the sheet show the quantity themselves.
 * :return: the new cart quantity of the header
 */
async function changeCartQuantity(templateId, productId, currentQuantity, delta) {
    let data;
    if (delta > 0) {
        data = await rpc("/shop/cart/add", { product_template_id: templateId, product_id: productId, quantity: 1 });
        // Same analytics event as the cart service of Odoo
        const shopEl = document.querySelector(".oe_website_sale");
        if (data.quantity && data.tracking_info && shopEl) {
            shopEl.dispatchEvent(new CustomEvent("add_to_cart_event", { detail: data.tracking_info }));
        }
    } else {
        data = await rpc("/shop/cart/update", {
            line_id: false,
            product_id: productId,
            quantity: Math.max(currentQuantity - 1, 0),
        });
    }
    updateCartIcon(data.cart_quantity || 0);
    return data;
}

/** Show the quantity of a card: "In cart · N" (several weights) or the stepper (one weight). */
function setCardQuantity(actionsEl, quantity) {
    if (!actionsEl) {
        return;
    }
    actionsEl.dataset.cartQty = String(quantity);
    const choose = actionsEl.querySelector(".o_journey_choose");
    if (choose) {
        choose.textContent = quantity ? _t("In cart · %s", quantity) : _t("Choose weight");
        choose.classList.toggle("btn-primary", !quantity);
        choose.classList.toggle("btn-outline-primary", !!quantity);
        return;
    }
    actionsEl.querySelector(".o_journey_add")?.classList.toggle("d-none", !!quantity);
    actionsEl.querySelector(".o_journey_tile_stepper")?.classList.toggle("d-none", !quantity);
    const qty = actionsEl.querySelector(".o_journey_tile_qty");
    if (qty) {
        qty.textContent = String(quantity);
    }
}

/**
 * Product card: "Add" and the stepper change the quantity of the only weight;
 * "Choose weight" / "In cart · N" opens the weight sheet.
 */
export class JourneyProductTile extends Interaction {
    static selector = ".o_journey_tile_actions";
    dynamicContent = {
        ".o_journey_add": { "t-on-click.prevent.stop": this.locked(() => this.change(1), true) },
        ".o_journey_tile_plus": { "t-on-click.prevent.stop": this.locked(() => this.change(1), true) },
        ".o_journey_tile_minus": { "t-on-click.prevent.stop": this.locked(() => this.change(-1), true) },
        ".o_journey_choose": { "t-on-click.prevent.stop": this.choose },
    };

    get templateId() {
        return parseInt(this.el.dataset.productTemplateId);
    }

    async change(delta) {
        const current = parseFloat(this.el.dataset.cartQty) || 0;
        await this.waitFor(changeCartQuantity(this.templateId, parseInt(this.el.dataset.productId), current, delta));
        setCardQuantity(this.el, Math.max(current + delta, 0));
    }

    choose() {
        document.dispatchEvent(new CustomEvent("journey:choose-weight", {
            detail: { templateId: this.templateId, actionsEl: this.el },
        }));
    }
}

/**
 * The weight sheet: each weight (variant) with its price; several weights
 * can be added. Out of stock weights cannot be added.
 */
export class JourneyWeightSheet extends Interaction {
    static selector = "#o_journey_weight_sheet";
    dynamicContent = {
        ".o_journey_sheet_body": { "t-on-click": this.locked(this.onBodyClick, true) },
    };

    setup() {
        this.modal = window.Modal.getOrCreateInstance(this.el);
        this.registerCleanup(() => this.modal.dispose());
        this.onChoose = (ev) => this.open(ev.detail);
        document.addEventListener("journey:choose-weight", this.onChoose);
        this.registerCleanup(() => document.removeEventListener("journey:choose-weight", this.onChoose));
    }

    async open({ templateId, actionsEl }) {
        this.templateId = templateId;
        this.actionsEl = actionsEl;
        await this.refresh();
        this.modal.show();
    }

    async refresh() {
        const result = await this.waitFor(rpc("/shop/journey/weights", { product_template_id: this.templateId }));
        this.el.querySelector(".o_journey_sheet_body").innerHTML = result.html;
        setCardQuantity(this.actionsEl, result.cart_qty);
    }

    async onBodyClick(ev) {
        const button = ev.target.closest(".o_journey_sheet_add, .o_journey_qty_plus, .o_journey_qty_minus");
        if (!button) {
            return;
        }
        const row = button.closest(".o_journey_weight_row");
        const delta = button.classList.contains("o_journey_qty_minus") ? -1 : 1;
        await this.waitFor(changeCartQuantity(
            this.templateId, parseInt(row.dataset.productId), parseFloat(row.dataset.cartQty) || 0, delta));
        await this.refresh();
    }
}

registry
    .category("public.interactions")
    .add("website_purchase_journey.product_tile", JourneyProductTile)
    .add("website_purchase_journey.weight_sheet", JourneyWeightSheet);
