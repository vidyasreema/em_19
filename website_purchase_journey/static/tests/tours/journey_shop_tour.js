import { registry } from "@web/core/registry";

const card = (name) => `form.oe_product_cart:has(a:contains('${name}'))`;

registry.category("web_tour.tours").add("journey_shop", {
    url: "/shop",
    steps: () => [
        {
            content: "Deliver to bar with the general message (no location yet)",
            trigger: ".o_journey_location_bar:contains('Same-day delivery in Abu Dhabi')",
        },
        {
            content: "Out of stock (ribbon): the button is disabled",
            trigger: `${card("TOUR Tomahawk")} .o_journey_out_of_stock:disabled`,
        },
        {
            content: "Several weights: the card shows 'from' the cheapest price",
            trigger: `${card("TOUR Ribeye")} .o_journey_from`,
        },
        {
            content: "Open the weight sheet",
            trigger: `${card("TOUR Ribeye")} .o_journey_choose`,
            run: "click",
        },
        {
            content: "The sheet lists the weights, the out of stock one disabled",
            trigger: "#o_journey_weight_sheet.show .o_journey_weight_row:contains('250 g') .o_journey_row_out_of_stock",
        },
        {
            content: "Add 500 g",
            trigger: "#o_journey_weight_sheet .o_journey_weight_row:contains('500 g') .o_journey_sheet_add",
            run: "click",
        },
        {
            content: "500 g is in the cart: the row shows a quantity stepper",
            trigger: "#o_journey_weight_sheet .o_journey_weight_row:contains('500 g') .o_journey_row_in_cart:contains('1')",
        },
        {
            trigger: "#o_journey_weight_sheet .o_journey_weight_row:contains('500 g') .o_journey_qty_plus",
            run: "click",
        },
        {
            trigger: "#o_journey_weight_sheet .o_journey_weight_row:contains('500 g') .o_journey_row_in_cart:contains('2')",
        },
        {
            content: "Remove one again",
            trigger: "#o_journey_weight_sheet .o_journey_weight_row:contains('500 g') .o_journey_qty_minus",
            run: "click",
        },
        {
            trigger: "#o_journey_weight_sheet .o_journey_weight_row:contains('500 g') .o_journey_row_in_cart:contains('1')",
        },
        {
            content: "Add 1 kg too: several weights of the same product",
            trigger: "#o_journey_weight_sheet .o_journey_weight_row:contains('1 kg') .o_journey_sheet_add",
            run: "click",
        },
        {
            trigger: "#o_journey_weight_sheet .o_journey_weight_row:contains('1 kg') .o_journey_row_in_cart:contains('1')",
        },
        {
            content: "No 'added to cart' popup piles up over the sheet",
            trigger: "body:not(:has(.o_notification))",
        },
        {
            content: "Close the sheet",
            trigger: "#o_journey_weight_sheet .modal-footer .btn-primary",
            run: "click",
        },
        {
            content: "The button of the card now reads In cart · 2",
            trigger: `${card("TOUR Ribeye")} .o_journey_choose:contains('In cart · 2')`,
        },
        {
            content: "One weight: direct Add",
            trigger: `${card("TOUR Sausages")} .o_journey_add`,
            run: "click",
        },
        {
            content: "The card shows a quantity stepper",
            trigger: `${card("TOUR Sausages")} .o_journey_tile_stepper:not(.d-none) .o_journey_tile_qty:contains('1')`,
        },
        {
            trigger: `${card("TOUR Sausages")} .o_journey_tile_plus`,
            run: "click",
        },
        {
            trigger: `${card("TOUR Sausages")} .o_journey_tile_qty:contains('2')`,
        },
        {
            trigger: `${card("TOUR Sausages")} .o_journey_tile_minus`,
            run: "click",
        },
        {
            trigger: `${card("TOUR Sausages")} .o_journey_tile_qty:contains('1')`,
        },
        {
            content: "No 'added to cart' popup from the card either",
            trigger: "body:not(:has(.o_notification))",
        },
        {
            content: "The cart counter of the header is updated",
            trigger: ".my_cart_quantity:contains('3')",
        },
        {
            content: "The View cart button at the bottom shows the quantity and the total",
            trigger: ".o_journey_cart_bar:not(.d-none):contains('View cart · 3 items')",
        },
        {
            content: "No delivery address yet: View cart asks for it first",
            trigger: ".o_journey_cart_bar[data-needs-address='1']",
            run: "click",
        },
        {
            content: "The Address details sheet opens on the shop",
            trigger: ".o_journey_address_modal.show:contains('Address details') .o_journey_address_save",
        },
        {
            trigger: ".o_journey_address_modal.show:contains('Set your delivery location')",
        },
        {
            content: "The pin is required",
            trigger: ".o_journey_address_modal .o_journey_address_save",
            run: "click",
        },
        {
            trigger: ".o_journey_address_modal .o_journey_field_error[data-field='pin']:contains('Set your delivery location first')",
        },
        {
            content: "Close the sheet (once it has finished opening)",
            trigger: ".o_journey_address_modal.show",
            async run() {
                await new Promise((resolve) => setTimeout(resolve, 500));
                window.Modal.getInstance(this.anchor).hide();
            },
        },
        {
            trigger: "body:not(:has(.o_journey_address_modal.show))",
        },
        {
            content: "Favourites: the heart on the card",
            trigger: `${card("TOUR Sausages")} .o_journey_fav:not(:disabled)`,
            run: "click",
        },
        {
            content: "Saved: full heart",
            trigger: `${card("TOUR Sausages")} .o_journey_fav:disabled .fa-heart`,
        },
    ],
});
