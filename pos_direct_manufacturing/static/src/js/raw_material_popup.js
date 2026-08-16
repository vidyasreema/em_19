/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";

export class RawMaterialPopup extends Component {
    static template = "pos_direct_manufacturing.RawMaterialPopup";
    static components = { Dialog, AutoComplete };
    static props = {
        close: Function,
        orderLine: { type: Object, optional: true },
        getPayload: { type: Function, optional: true },
        existingMaterials: { type: Array, optional: true },
        productQty: { type: Number, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.pos = usePos();

        const initialLines = (this.props.existingMaterials || []).map((m, index) => ({
            id: index + 1,
            productId: m.productId,
            productName: m.productName,
            qty: m.qty,
        }));

        // The actual set of lines the popup starts with, whether that's
        // the existing materials or the empty-state placeholder row.
        const lines = initialLines.length
            ? initialLines
            : [{ id: 1, productId: null, productName: "", qty: 0 }];

        this.state = useState({
            lines,
            errorMessage: "",
        });

        // Base nextLineId on the ids actually present in `lines`, not on
        // `initialLines` (which can be empty even though `lines` isn't).
        // Using initialLines.length here was the bug: it produced
        // nextLineId = 1 whenever existingMaterials was empty, colliding
        // with the placeholder line's id of 1 as soon as a line was added.
        this.nextLineId = lines.length
            ? Math.max(...lines.map((l) => l.id)) + 1
            : 1;
    }

    getSources(line) {
        return [
            {
                options: (searchTerm) => this.loadProductOptions(line, searchTerm),
            },
        ];
    }

    async loadProductOptions(line, searchTerm) {
        const results = await this.orm.call(
            "product.product",
            "search_pos_raw_materials",
            [this.pos.config.id, searchTerm || ""],
            { limit: searchTerm ? 10 : 20 }
        );
        return results.map((p) => ({
            label: p.display_name,
            onSelect: () => {
                line.productId = p.id;
                line.productName = p.display_name;
                this.state.errorMessage = "";
            },
        }));
    }

    onQtyChange(line, ev) {
        line.qty = parseFloat(ev.target.value) || 0;
        this.state.errorMessage = "";
    }

    onAddLine() {
        this.state.lines.push({
            id: this.nextLineId++,
            productId: null,
            productName: "",
            qty: 0,
        });
    }

    onRemoveLine(lineId) {
        this.state.lines = this.state.lines.filter((l) => l.id !== lineId);
        this.state.errorMessage = "";
    }

    onConfirm() {
        const invalidLines = this.state.lines.filter(
            (l) => l.productId && l.qty <= 0
        );
        if (invalidLines.length > 0) {
            this.state.errorMessage =
                "Please enter a quantity greater than 0 for each selected material.";
            return;
        }

        const validLines = this.state.lines.filter(
            (l) => l.productId && l.qty > 0
        );
        if (validLines.length === 0) {
            this.state.errorMessage =
                "Please select at least one raw material with a quantity.";
            return;
        }

        const totalQty = validLines.reduce((sum, l) => sum + l.qty, 0);
        if (this.props.productQty && totalQty > this.props.productQty) {
            this.state.errorMessage =
                `Total raw material quantity (${totalQty}) cannot exceed the product quantity (${this.props.productQty}).`;
            return;
        }

        if (this.props.getPayload) {
            this.props.getPayload(validLines);
        }
        this.props.close();
    }

    onCancel() {
        this.props.close();
    }
}