import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("journey_order", {
    url: "/shop/order",
    steps: () => [
        {
            content: "The delivery time popup opens (first time this promise is shown)",
            trigger: ".o_journey_promise_modal.show:contains('Delivered today within 3 hours') .o_journey_promise_date:contains('· by ')",
        },
        {
            content: "Got it (once the popup has finished opening)",
            trigger: ".o_journey_promise_modal.show .btn-primary",
            async run(helpers) {
                await new Promise((resolve) => setTimeout(resolve, 500));
                await helpers.click();
            },
        },
        {
            content: "The popup is closed",
            trigger: "body:not(:has(.modal.show)):not(.modal-open)",
        },
        {
            content: "Signed in: no sign-up box",
            trigger: ".o_journey_order:contains('Signed in as'):not(:has(.o_journey_gbox))",
        },
        {
            content: "The welcome coupon was applied after signing up",
            trigger: ".o_journey_coupon_ok:contains('applied on the full amount')",
        },
        {
            content: "Free delivery progress and the promise",
            trigger: ".o_journey_progress:contains('to get free delivery')",
        },
        {
            trigger: ".o_journey_promise_line:contains('Delivered today within 3 hours')",
        },
        {
            content: "One more unit from the cart of the page",
            trigger: ".o_journey_cart_line .o_journey_line_plus",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "After the reload: same promise, no popup again",
            trigger: ".o_journey_cart_line .o_journey_row_in_cart:contains('381')",
        },
        {
            trigger: "body:not(:has(.o_journey_promise_modal.show))",
        },
        {
            content: "Opening the order page again shows the popup again",
            trigger: ".o_journey_order",
            run: "goToUrl /shop/order",
            expectUnloadPage: true,
        },
        {
            trigger: ".o_journey_promise_modal.show .btn-primary",
            async run(helpers) {
                await new Promise((resolve) => setTimeout(resolve, 500));
                await helpers.click();
            },
        },
        {
            trigger: "body:not(:has(.modal.show)):not(.modal-open)",
        },
        {
            content: "Received by: Change opens the Address details sheet with the address",
            trigger: ".o_journey_blk:contains('Received by') .o_journey_address_open",
            run: "click",
        },
        {
            trigger: ".o_journey_address_modal.show .o_journey_address_area:contains('Apt 5')",
        },
        {
            content: "The apartment is required",
            trigger: ".o_journey_address_modal.show .o_journey_address_save",
            async run(helpers) {
                await new Promise((resolve) => setTimeout(resolve, 500));
                await helpers.click();
            },
        },
        {
            trigger: ".o_journey_address_modal .o_journey_field_bad .o_journey_field_error:contains('apartment or villa number')",
        },
        {
            trigger: ".o_journey_address_modal input[name='apartment']",
            run: "edit Apt 5",
        },
        {
            content: "Someone else receives the order",
            trigger: ".o_journey_address_modal input[name='name']",
            run: "edit Mona Gift",
        },
        {
            trigger: ".o_journey_address_modal .o_journey_address_save",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Saved: the order page shows the receiver and the address, no popup again (same promise)",
            trigger: ".o_journey_blk:contains('Received by'):contains('Mona Gift')",
        },
        {
            trigger: ".o_journey_address:contains('Apt 5, Tower A')",
        },
        {
            trigger: "body:not(:has(.modal.show))",
        },
        {
            content: "A wrong code",
            trigger: ".o_journey_coupon_code",
            run: "edit NOPE",
        },
        {
            trigger: ".o_journey_coupon_apply",
            run: "click",
            expectUnloadPage: true,
        },
        {
            trigger: ".o_journey_coupon_error:contains('Check the spelling')",
        },
        {
            content: "Instructions for the driver",
            trigger: ".o_journey_chip[data-key='leave_at_door']",
            run: "click",
        },
        {
            trigger: ".o_journey_chip[data-key='leave_at_door'][aria-pressed='true']",
        },
        {
            trigger: ".o_journey_note",
            run: "edit Gate 2, then the lift",
        },
        {
            content: "Explicit consent (unticked by default)",
            trigger: ".o_journey_consent:not(:checked)",
            run: "click",
        },
        {
            content: "The payment form of Odoo (one method, selected) enables the order button",
            trigger: "button[name='o_payment_submit_button']:contains('Place order'):enabled",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Order placed",
            trigger: "#order_name",
        },
        {
            content: "The confirmation page shows the promise and its date",
            trigger: ".o_delivery_promise_confirmation:contains('Delivered today within 3 hours'):contains('· by ')",
        },
    ],
});
