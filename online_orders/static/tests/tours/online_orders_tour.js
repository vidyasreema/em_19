import { registry } from "@web/core/registry";

const column = (name) => `.o_kanban_group:has(.o_column_title:contains('${name}'))`;
const card = (name) => `.o_kanban_record:contains('${name}')`;

registry.category("web_tour.tours").add("online_orders_board", {
    steps: () => [
        {
            content: "Counters are shown on top of the board",
            trigger: ".o_online_orders_counters .o_online_counter_open:contains('Open:')",
        },
        {
            content: "Next-stage button of a card",
            trigger: `${column("New")} ${card("TOUR-A")} .o_online_next_stage`,
            run: "click",
        },
        {
            content: "The move asks for confirmation",
            trigger: ".modal-footer .btn-primary",
            run: "click",
        },
        {
            content: "TOUR-A is out for delivery",
            trigger: `${column("Out for Delivery")} ${card("TOUR-A")}`,
        },
        {
            content: "Drag TOUR-A to Delivered",
            trigger: card("TOUR-A"),
            run: `drag_and_drop(${column("Delivered")})`,
        },
        {
            content: "Confirmation dialog of the drag",
            trigger: ".modal-body:contains('Move TOUR-A to Delivered?')",
        },
        {
            trigger: ".modal-footer .btn-primary",
            run: "click",
        },
        {
            content: "TOUR-A is delivered",
            trigger: `${column("Delivered")} ${card("TOUR-A")}`,
        },
        {
            content: "Drag TOUR-B, then refuse the move",
            trigger: card("TOUR-B"),
            run: `drag_and_drop(${column("Out for Delivery")})`,
        },
        {
            trigger: ".modal-footer .btn-secondary",
            run: "click",
        },
        {
            content: "TOUR-B stayed in New",
            trigger: `${column("New")} ${card("TOUR-B")}`,
        },
        {
            content: "Drag TOUR-B to the Cancelled column",
            trigger: card("TOUR-B"),
            run: `drag_and_drop(${column("Cancelled")})`,
        },
        {
            content: "The cancellation dialog asks for a reason",
            trigger: ".modal .o_field_widget[name='reason'] input[data-value='customer']",
            run: "click",
        },
        {
            trigger: ".modal button[name='action_cancel_order']",
            run: "click",
        },
        {
            content: "TOUR-B left the New column",
            trigger: `${column("New")}:not(:has(${card("TOUR-B")}))`,
        },
    ],
});
