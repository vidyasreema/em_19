import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("collections_workbench_table_tour", {
    steps: () => [
        { trigger: ".o_cw_workbench .o_cw_summary" },
        { trigger: ".o_cw_table .o_cw_row" },
        { trigger: ".o_cw_th_label:contains(Total due)", run: "click" },
        { trigger: ".o_cw_menu button:contains(Sort descending)", run: "click" },
        { trigger: ".o_cw_th_label:contains(Assigned to)", run: "click" },
        { trigger: ".o_cw_menu button:contains(Hide column)", run: "click" },
        { trigger: ".o_cw_add_area button:contains(Columns)", run: "click" },
        { trigger: ".o_cw_add_area button:contains(Assigned to)", run: "click" },
        { trigger: ".o_cw_workbench button:contains(Panel)", run: "click" },
        { trigger: ".o_cw_panel_inner .nav-link:contains(Internal discussion)", run: "click" },
        { trigger: ".o_cw_chatter .o-mail-Chatter" },
        { trigger: ".o_cw_panel_inner .nav-link:contains(Customer emails)", run: "click" },
        { trigger: ".o_cw_panel_inner .nav-link:contains(Customer)", run: "click" },
        { trigger: ".o_cw_panel_inner button:contains(Follow up)", run: "click" },
        { trigger: ".modal .o_field_widget[name=kind]" },
        { trigger: ".modal button:contains(Cancel)", run: "click" },
        { trigger: ".o_cw_workbench:not(:has(.modal))" },
    ],
});

registry.category("web_tour.tours").add("collections_workbench_board_tour", {
    steps: () => [
        { trigger: ".o_cw_board_tabs button:contains(Approvals)" },
        { trigger: ".o_kanban_record button:contains(Follow up)", run: "click" },
        { trigger: ".modal .o_field_widget[name=stage_id]" },
        { trigger: ".modal button:contains(Cancel)", run: "click" },
        { trigger: ".o_cw_board_tabs button:contains(Legal Cases)", run: "click" },
        { trigger: ".o_cw_board_tabs button.btn-primary:contains(Legal Cases)" },
    ],
});

registry.category("web_tour.tours").add("collections_workbench_dashboard_tour", {
    steps: () => [
        { trigger: ".o_cw_dashboard .o_cw_card" },
        { trigger: ".o_cw_dashboard button:contains(Team)", run: "click" },
        { trigger: ".o_cw_dashboard .o_cw_card:contains(Ready to send)", run: "click" },
        { trigger: ".o_cw_workbench .o_searchview_facet:contains(Due to send)" },
        // the team view opens everyone's customers, not "My customers"
        { trigger: ".o_cw_workbench .o_searchview:not(:has(.o_searchview_facet:contains(My customers)))" },
    ],
});

registry.category("web_tour.tours").add("collections_workbench_report_tour", {
    steps: () => [
        { trigger: ".o_cw_report .o_cw_kpi:contains(Rate: net amount)" },
        { trigger: ".o_cw_report .o_cw_kpi:contains(Avg days to close)" },
        { trigger: ".o_cw_report tr:contains(Net total)" },
        { trigger: ".o_cw_report th:contains(Share)" },
        { trigger: ".o_cw_report .o_cw_bar_row" },
        { trigger: ".o_cw_report button:contains(Email report)", run: "click" },
        { trigger: ".modal .o_form_view" },
        { trigger: ".modal button:contains(Cancel), .modal button:contains(Discard)", run: "click" },
        { trigger: ".o_cw_report:not(:has(.modal))" },
    ],
});

registry.category("web_tour.tours").add("collections_workbench_assign_tour", {
    steps: () => [
        { trigger: ".o_cw_row input[type=checkbox]", run: "click" },
        { trigger: ".o_cw_workbench button:contains(Change assignee)", run: "click" },
        { trigger: ".modal .o_field_widget[name=employee_id]" },
        { trigger: ".modal button:contains(Cancel)", run: "click" },
        { trigger: ".o_cw_workbench:not(:has(.modal))" },
    ],
});
