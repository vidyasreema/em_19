import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { CartonScanDialog } from "./carton_scan_dialog";
import { CARTON_CONFIG, ensureLineSaved, isLineReadonly } from "./utils";

/** Barcode button of an operation or count line: opens the carton scan window. */
export class CartonScanButton extends Component {
    static template = "stock_barcode_register.CartonScanButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.dialog = useService("dialog");
        this.notification = useService("notification");
    }

    get count() {
        return this.props.record.data.carton_count || 0;
    }

    async onClick(ev) {
        ev.stopPropagation();
        const record = this.props.record;
        const lineId = await ensureLineSaved(record, this.notification);
        if (!lineId) {
            return;
        }
        const root = record.model.root;
        const config = CARTON_CONFIG[record.resModel];
        const product = record.data.product_id;
        this.dialog.add(CartonScanDialog, {
            resModel: config.resModel,
            parentField: config.parentField,
            parentId: lineId,
            productId: product.id,
            productName: product.display_name,
            readonly: isLineReadonly(record),
            isReceipt: root.data.picking_type_code === "incoming",
            hint: root.data.picking_type_code === "incoming" ? root.data.vendor_barcode_hint || false : false,
            onChanged: async () => {
                // The product lines behind the window update live
                await root.load();
            },
        });
    }
}

registry.category("view_widgets").add("carton_scan_button", {
    component: CartonScanButton,
});
