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
        productUomId: { type: [Number, { value: null }], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.pos = usePos();

        const initialLines = (this.props.existingMaterials || []).map((m, index) => ({
            id: index + 1,
            productId: m.productId,
            productName: m.productName,
            qty: m.qty,
            uomId: m.uomId || null,
        }));

        // The actual set of lines the popup starts with, whether that's
        // the existing materials or the empty-state placeholder row.
        const lines = initialLines.length
            ? initialLines
            : [{ id: 1, productId: null, productName: "", qty: 0, uomId: null }];

        this.state = useState({
            lines,
            errorMessage: "",
            // Set once a below-tolerance total has been shown to the cashier.
            // The next Confirm goes through: too little raw material is a
            // warning, not a block, because trim and bone loss are real.
            lowTotalAcknowledged: false,
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
                line.uomId = p.uom_id || null;
                this.state.errorMessage = "";
                this.state.lowTotalAcknowledged = false;
            },
        }));
    }

    onQtyChange(line, ev) {
        line.qty = parseFloat(ev.target.value) || 0;
        this.state.errorMessage = "";
        this.state.lowTotalAcknowledged = false;
    }

    onAddLine() {
        this.state.lines.push({
            id: this.nextLineId++,
            productId: null,
            productName: "",
            qty: 0,
            uomId: null,
        });
    }

    onRemoveLine(lineId) {
        this.state.lines = this.state.lines.filter((l) => l.id !== lineId);
        this.state.errorMessage = "";
        this.state.lowTotalAcknowledged = false;
    }

    /**
     * Two units can be compared only when they share a reference unit.
     * Odoo 19 keeps units in a tree and stores the path on each record, so
     * a shared root is what makes a conversion possible. kg and g convert;
     * kg and Units do not.
     */
    _uomsAreComparable(uomA, uomB) {
        if (!uomA || !uomB || !uomA.parent_path || !uomB.parent_path) {
            return false;
        }
        return uomA.parent_path.split("/")[0] === uomB.parent_path.split("/")[0];
    }

    /**
     * Total of all raw material quantities expressed in the finished
     * product's unit. Returns null when the comparison does not apply —
     * no unit on the finished product, or a material whose unit cannot be
     * converted into it (kg of meat for a product sold in Units).
     */
    _getConvertedTotal(validLines) {
        const uomModel = this.pos.models["uom.uom"];
        if (!uomModel || !this.props.productUomId) {
            return null;
        }
        const targetUom = uomModel.get(this.props.productUomId);
        if (!targetUom || !targetUom.factor) {
            return null;
        }

        let total = 0;
        for (const line of validLines) {
            if (!line.uomId) {
                return null;
            }
            const lineUom = uomModel.get(line.uomId);
            if (!lineUom || !this._uomsAreComparable(lineUom, targetUom)) {
                return null;
            }
            // Same formula as UomUom._compute_quantity on the server.
            total += (line.qty * lineUom.factor) / targetUom.factor;
        }
        return total;
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

        const totalQty = this._getConvertedTotal(validLines);
        // totalQty is null when the units are not convertible: comparing
        // kilos of meat against a count of burgers has no correct answer,
        // so the check is skipped rather than guessed at.
        if (totalQty !== null && this.props.productQty) {
            const tolerance = this.pos.config.raw_material_tolerance || 0;
            const rounded = Math.round(totalQty * 1000) / 1000;

            if (rounded > this.props.productQty + tolerance) {
                this.state.errorMessage =
                    `Total raw material quantity (${rounded}) cannot exceed the product quantity (${this.props.productQty}) by more than ${tolerance}.`;
                return;
            }

            if (
                rounded < this.props.productQty - tolerance &&
                !this.state.lowTotalAcknowledged
            ) {
                this.state.errorMessage =
                    `Total raw material quantity (${rounded}) is well below the product quantity (${this.props.productQty}). Press Confirm again to continue anyway.`;
                this.state.lowTotalAcknowledged = true;
                return;
            }
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