import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { errorMessage } from "./utils";

const TYPE_LABELS = {
    gs1: "GS1",
    template: _t("Template"),
    manual: _t("Manual"),
    fixed: _t("Fixed"),
    generated: _t("Generated"),
};

/**
 * Carton scan window: row-by-row entry inside a table, an empty row at the bottom,
 * a new one opens after each confirmation. Every row is saved immediately.
 */
export class CartonScanDialog extends Component {
    static template = "stock_barcode_register.CartonScanDialog";
    static components = { Dialog };
    static props = {
        resModel: String,
        parentField: String,
        parentId: Number,
        productId: Number,
        productName: String,
        readonly: { type: Boolean, optional: true },
        isReceipt: { type: Boolean, optional: true },
        hint: { type: [String, { value: false }], optional: true },
        onChanged: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.barcodeRef = useRef("barcode");
        this.quantityRef = useRef("quantity");
        this.typeLabels = TYPE_LABELS;
        this.state = useState({ rows: [], entry: this.emptyEntry(), busy: false });
        onWillStart(() => this.load());
        onMounted(() => this.focus(this.barcodeRef));
    }

    get isMoveCarton() {
        return this.props.resModel === "stock.move.carton";
    }

    get title() {
        return _t("Cartons: %s", this.props.productName);
    }

    get totals() {
        return {
            quantity: this.state.rows.reduce((sum, row) => sum + (row.quantity || 0), 0),
            cartons: this.state.rows.reduce((sum, row) => sum + (row.carton_count || 0), 0),
        };
    }

    get readFields() {
        const fields = ["barcode", "barcode_type", "quantity", "carton_count", "pack_date", "carton_number"];
        if (this.isMoveCarton) {
            fields.push("alert_date", "pack_date_estimated", "alert_date_manual");
        } else {
            fields.push("register_id");
        }
        return fields;
    }

    emptyEntry() {
        return {
            barcode: "",
            barcode_type: "manual",
            quantity: "",
            carton_count: 1,
            pack_date: "",
            alert_date: "",
            carton_number: false,
            product_code: false,
            template_id: false,
            parsedBarcode: false,
        };
    }

    focus(ref) {
        ref.el?.focus();
        ref.el?.select?.();
    }

    formatQuantity(value) {
        return (value || 0).toLocaleString(undefined, { maximumFractionDigits: 3 });
    }

    async load() {
        this.state.rows = await this.orm.searchRead(
            this.props.resModel,
            [[this.props.parentField, "=", this.props.parentId]],
            this.readFields,
            { order: "sequence, id" }
        );
    }

    async afterChange() {
        await this.load();
        await this.props.onChanged();
    }

    async readBarcode() {
        const entry = this.state.entry;
        const barcode = entry.barcode.trim();
        if (!barcode) {
            this.focus(this.quantityRef);
            return;
        }
        if (entry.parsedBarcode === barcode) {
            return;
        }
        entry.parsedBarcode = barcode; // guards against Enter + change reading twice
        let result;
        try {
            result = await this.orm.call(this.props.resModel, "parse_barcode", [barcode, this.props.productId]);
        } catch (error) {
            entry.parsedBarcode = false;
            throw error;
        }
        Object.assign(entry, {
            barcode,
            barcode_type: result.barcode_type,
            carton_number: result.carton_number || false,
            product_code: result.product_code || false,
            template_id: result.template_id || false,
        });
        if (result.quantity) {
            entry.quantity = result.quantity;
        }
        if (result.pack_date) {
            entry.pack_date = result.pack_date;
        }
        if (result.barcode_type === "gs1" && result.quantity) {
            // GS1: the row fills and saves itself
            await this.saveEntry();
        } else {
            // Template: known fields fill, the rest is requested. Manual: quantity and pack date are typed.
            this.focus(this.quantityRef);
        }
    }

    async onBarcodeKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            ev.stopPropagation();
            await this.readBarcode();
        }
    }

    async onEntryKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            ev.stopPropagation();
            await this.saveEntry();
        }
    }

    async saveEntry() {
        if (this.state.busy) {
            return;
        }
        let entry = this.state.entry;
        if (entry.barcode.trim() && entry.parsedBarcode !== entry.barcode.trim()) {
            await this.readBarcode();
            if (this.state.entry !== entry) {
                return; // a GS1 row was saved by readBarcode
            }
        }
        const quantity = parseFloat(entry.quantity) || 0;
        if (!entry.barcode.trim() && !this.props.isReceipt) {
            this.notification.add(_t("Scan or type the carton barcode."), { type: "warning" });
            this.focus(this.barcodeRef);
            return;
        }
        if (this.props.isReceipt && quantity <= 0) {
            this.notification.add(_t("Enter the carton quantity."), { type: "warning" });
            this.focus(this.quantityRef);
            return;
        }
        const vals = {
            [this.props.parentField]: this.props.parentId,
            barcode: entry.barcode.trim() || false,
            barcode_type: entry.barcode_type,
            quantity,
            carton_count: parseInt(entry.carton_count) || 1,
            pack_date: entry.pack_date || false,
            carton_number: entry.carton_number,
            product_code: entry.product_code,
            template_id: entry.template_id,
        };
        if (this.isMoveCarton && entry.alert_date) {
            vals.alert_date = entry.alert_date;
        }
        this.state.busy = true;
        try {
            await this.orm.create(this.props.resModel, [vals]);
            this.state.entry = this.emptyEntry();
            await this.afterChange();
        } catch (error) {
            this.notification.add(errorMessage(error), { type: "danger" });
        } finally {
            this.state.busy = false;
            this.focus(this.barcodeRef);
        }
    }

    async onDone() {
        const entry = this.state.entry;
        if (!this.props.readonly && (entry.barcode.trim() || parseFloat(entry.quantity))) {
            // A typed row not yet confirmed with Enter is saved, not lost
            await this.saveEntry();
            if (this.state.entry === entry) {
                return; // not saved: the warning is shown and the window stays open
            }
        }
        this.props.close();
    }

    async updateRow(row, field, value) {
        try {
            await this.orm.write(this.props.resModel, [row.id], { [field]: value || false });
        } catch (error) {
            this.notification.add(errorMessage(error), { type: "danger" });
        }
        await this.afterChange();
    }

    async deleteRow(row) {
        try {
            await this.orm.unlink(this.props.resModel, [row.id]);
        } catch (error) {
            this.notification.add(errorMessage(error), { type: "danger" });
        }
        await this.afterChange();
        this.focus(this.barcodeRef);
    }
}
