import { registry } from "@web/core/registry";

const GS1 = "01094123456789043102001175132610012199001";

registry.category("web_tour.tours").add("stock_barcode_register_receipt_scan", {
    steps: () => [
        {
            content: "Open the carton scan window of the line",
            trigger: ".o_carton_scan_button",
            run: "click",
        },
        {
            content: "Scan a GS1 carton",
            trigger: ".o_carton_scan_dialog .o_carton_entry_row input[type=text]",
            run: `edit ${GS1}`,
        },
        {
            trigger: ".o_carton_scan_dialog .o_carton_entry_row input[type=text]",
            run: "press Enter",
        },
        {
            content: "The GS1 row fills and saves itself",
            trigger: ".o_carton_scan_dialog tbody tr:not(.o_carton_entry_row) td:contains('GS1')",
        },
        {
            content: "Type a manual barcode",
            trigger: ".o_carton_scan_dialog .o_carton_entry_row input[type=text]",
            run: "edit AGRA-0001",
        },
        {
            trigger: ".o_carton_scan_dialog .o_carton_entry_row input[type=text]",
            run: "press Enter",
        },
        {
            content: "Type the quantity",
            trigger: ".o_carton_scan_dialog .o_carton_entry_row input[type=number]:first",
            run: "edit 12",
        },
        {
            trigger: ".o_carton_scan_dialog .o_carton_entry_row input[type=number]:first",
            run: "press Enter",
        },
        {
            content: "Two cartons saved, receipt date used as estimated pack date",
            trigger: ".o_carton_scan_dialog tbody tr:not(.o_carton_entry_row):eq(1) .badge:contains('Estimated')",
        },
        {
            trigger: ".o_carton_scan_dialog tfoot td:contains('23.75')",
        },
        {
            content: "A carton without a label: quantity only, no Enter",
            trigger: ".o_carton_scan_dialog .o_carton_entry_row input[type=number]:first",
            run: "edit 2",
        },
        {
            content: "Done saves the typed row before closing",
            trigger: ".o_carton_scan_dialog .modal-footer .btn-primary",
            run: "click",
        },
        {
            content: "The line updated behind the window",
            trigger: ".o_carton_scan_button:contains('3')",
        },
        {
            trigger: ".o_carton_photos button[title='Take a photo']",
        },
    ],
});

registry.category("web_tour.tours").add("stock_barcode_register_count_scan", {
    steps: () => [
        {
            trigger: ".o_carton_scan_button",
            run: "click",
        },
        {
            trigger: ".o_carton_scan_dialog .o_carton_entry_row input[type=text]",
            run: "edit C-REG-1",
        },
        {
            trigger: ".o_carton_scan_dialog .o_carton_entry_row input[type=text]",
            run: "press Enter",
        },
        {
            content: "Quantity comes from the register: just confirm the row",
            trigger: ".o_carton_scan_dialog .o_carton_entry_row button[title='Confirm row']",
            run: "click",
        },
        {
            content: "Matched with its register row",
            trigger: ".o_carton_scan_dialog tbody tr:not(.o_carton_entry_row) td:contains('C-REG-1'):eq(1)",
        },
        {
            trigger: ".o_carton_scan_dialog .modal-footer .btn-primary",
            run: "click",
        },
        {
            trigger: ".o_carton_scan_button:contains('1')",
        },
    ],
});
