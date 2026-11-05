import { registry } from "@web/core/registry";

const row = (name) => `.o_online_availability_row:contains('${name}')`;

registry.category("web_tour.tours").add("online_orders_product_availability", {
    steps: () => [
        {
            content: "Search the product",
            trigger: ".o_online_availability_search input",
            run: "edit Tour Wagyu",
        },
        {
            content: "Counts follow the search: 2 products, both available",
            trigger: ".o_online_filter_all:contains('2') ~ .o_online_filter_available:contains('2') ~ .o_online_filter_out_of_stock:contains('0')",
        },
        {
            content: "Tap the switch of Tour Wagyu Rump",
            trigger: `${row("Tour Wagyu Rump")} .o_online_availability_switch.o_on:contains('AVAILABLE')`,
            run: "click",
        },
        {
            content: "Saved at once, with a message",
            trigger: ".o_notification:contains('Saved: Tour Wagyu Rump is out of stock')",
        },
        {
            content: "The switch is black, the name grey",
            trigger: `${row("Tour Wagyu Rump")}.o_out_of_stock .o_online_availability_switch.o_off:contains('OUT OF STOCK')`,
        },
        {
            content: "Out of stock filter",
            trigger: ".o_online_filter_out_of_stock:contains('1')",
            run: "click",
        },
        {
            content: "Only the out-of-stock product is listed",
            trigger: `.o_online_availability_list:has(${row("Tour Wagyu Rump")}):not(:has(${row("Tour Wagyu Ribeye")}))`,
        },
        {
            content: "Switch it back",
            trigger: `${row("Tour Wagyu Rump")} .o_online_availability_switch.o_off`,
            run: "click",
        },
        {
            trigger: ".o_notification:contains('Saved: Tour Wagyu Rump is available')",
        },
        {
            content: "It leaves the Out of stock list",
            trigger: `.o_online_availability_list:not(:has(${row("Tour Wagyu Rump")}))`,
        },
        {
            content: "Mark the ribeye out of stock (checked on the website by the test)",
            trigger: ".o_online_filter_all",
            run: "click",
        },
        {
            trigger: `${row("Tour Wagyu Ribeye")} .o_online_availability_switch.o_on`,
            run: "click",
        },
        {
            trigger: `${row("Tour Wagyu Ribeye")}.o_out_of_stock`,
        },
        {
            trigger: ".o_notification:contains('Saved: Tour Wagyu Ribeye is out of stock')",
        },
    ],
});
