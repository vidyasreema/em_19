import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("journey_order_guest", {
    url: "/shop",
    steps: () => [
        {
            content: "Add a product from the shop",
            trigger: "form.oe_product_cart:has(a:contains('TOUR Sausages')) .o_journey_add",
            run: "click",
        },
        {
            trigger: "form.oe_product_cart:has(a:contains('TOUR Sausages')) .o_journey_tile_qty:contains('1')",
        },
        {
            content: "Go to the order page",
            trigger: "body",
            run: () => { window.location.href = "/shop/order"; },
            expectUnloadPage: true,
        },
        {
            content: "Guests see the sign-up box with the saving",
            trigger: ".o_journey_gbox:contains('New here? Sign up and get 10% off'):contains('You save')",
        },
        {
            trigger: ".o_journey_guest_go",
            run: "click",
        },
        {
            content: "The box shrinks to one line",
            trigger: ".o_journey_gline:not(.d-none):contains('Checking out as guest')",
        },
        {
            trigger: ".o_journey_email",
            run: "edit guest@example.com",
        },
        {
            content: "Place order without an address",
            trigger: "button[name='o_payment_submit_button']:enabled",
            run: "click",
        },
        {
            content: "The address is asked for",
            trigger: ".o_journey_form_error:not(.d-none):contains('Add your delivery address')",
        },
        {
            content: "Sign up again from the line",
            trigger: ".o_journey_gline .o_journey_show_signup",
            run: "click",
        },
        {
            trigger: ".o_journey_gbox:not(.d-none)",
        },
    ],
});
