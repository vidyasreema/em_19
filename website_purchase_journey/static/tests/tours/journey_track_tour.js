import { registry } from "@web/core/registry";

// My orders > Track > Order again
registry.category("web_tour.tours").add("journey_track", {
    steps: () => [
        {
            content: "My orders: Track and Order again on the open order",
            trigger: "tr:has(.o_journey_reorder) .o_journey_track_btn:contains('Track')",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Track your order: items, promise and the first step done",
            trigger: ".o_journey_track_page:contains('Track your order'):contains('TOUR Mince (unit)'):has(.o_journey_track_step_on:contains('Order received'))",
        },
        {
            trigger: ".o_journey_track_page:not(:has(.o_journey_track_step_on:contains('Out for delivery')))",
        },
        {
            content: "Order again",
            trigger: ".o_journey_track_page .o_journey_reorder",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "The products are back in the cart of the order page",
            trigger: ".o_journey_order .o_journey_cart_line:contains('TOUR Mince (unit)')",
        },
        {
            content: "Order again with products in the cart",
            trigger: "body",
            run: "goToUrl /my/orders",
            expectUnloadPage: true,
        },
        {
            trigger: "tr:not(.d-md-none) .o_journey_reorder",
            run: "click",
        },
        {
            content: "The customer chooses: replace the cart",
            trigger: ".modal:contains('Your cart already has products') .modal-footer .btn-primary:contains('Replace with this order')",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "The cart is the past order (not twice its quantities)",
            trigger: ".o_journey_order .o_journey_cart_line:contains('TOUR Mince (unit)')",
        },
    ],
});
