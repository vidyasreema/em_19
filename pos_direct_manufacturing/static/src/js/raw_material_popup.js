/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import {
    compareRawMaterialTotal,
    getConvertedRawMaterialTotal,
} from "@pos_direct_manufacturing/js/raw_material_utils";

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
        enforcement: { type: String, optional: true },
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
            // Set when the total is below the product quantity: the next
            // Confirm saves anyway. Cleared as soon as anything is edited.
            warningMessage: "",
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
            onSelect: async () => {
                line.productId = p.id;
                line.productName = p.display_name;
                line.uomId = p.uom_id || null;
                this._clearMessages();

                // search_pos_raw_materials searches the whole catalogue and
                // deliberately ignores available_in_pos: a raw material such
                // as a carcass or a primal is never sold over the counter,
                // so filtering on it would hide exactly what the cashier
                // needs to pick. The consequence is that the chosen product
                // may not be loaded in this POS session.
                //
                // It has to be pulled in here. Without a record behind the
                // id, the relational field on pos.order.line.raw.material
                // has nothing to point at: it serialises as NULL, the
                // not-null constraint rejects the INSERT, and the whole
                // order sync fails at the payment screen.
                await this._ensureProductLoaded(p.id);
            },
        }));
    }

    /**
     * Make sure a product.product record exists in the POS store for the
     * given id, fetching it from the server if the session did not load it.
     *
     * Returns the record, or null if it could not be loaded.
     */
    async _ensureProductLoaded(productId) {
        const productModel = this.pos.models["product.product"];
        if (!productId || !productModel) {
            return null;
        }
        const existing = productModel.get(productId);
        if (existing) {
            return existing;
        }
        try {
            await this.pos.data.read("product.product", [productId]);
        } catch (error) {
            console.warn(
                "[pos_direct_manufacturing] could not load product %s into the " +
                    "POS session:",
                productId,
                error
            );
            return null;
        }
        return productModel.get(productId) || null;
    }

    onQtyChange(line, ev) {
        line.qty = parseFloat(ev.target.value) || 0;
        this._clearMessages();
    }

    _clearMessages() {
        this.state.errorMessage = "";
        this.state.warningMessage = "";
    }

    onAddLine() {
        this._clearMessages();
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
        this._clearMessages();
    }

    /**
     * The unit of a popup line.
     *
     * Raw material records created earlier in this session have no uom_id:
     * it is a related field filled in on the server, so it only appears
     * after a round trip. Falling back to the product's own unit keeps the
     * quantity check alive when the popup is reopened — without it, every
     * reopened line looked "not comparable" and the check was skipped
     * entirely, accepting any quantity.
     */
    _resolveUomId(line) {
        if (line.uomId) {
            return line.uomId;
        }
        const product = this.pos.models["product.product"]?.get(line.productId);
        return (
            product?.uom_id?.id ||
            product?.product_tmpl_id?.uom_id?.id ||
            null
        );
    }

    /**
     * Total of all raw material quantities expressed in the finished
     * product's unit, or null when the units cannot be compared.
     */
    _getConvertedTotal(validLines) {
        return getConvertedRawMaterialTotal(
            this.pos.models["uom.uom"],
            validLines.map((line) => ({ qty: line.qty, uomId: this._resolveUomId(line) })),
            this.props.productUomId
        );
    }

    async onConfirm() {
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

        // Second chance for anything that slipped past onSelect, such as a
        // line restored from an order line saved before this fix shipped.
        // Better to refuse here, in the popup, than to let the cashier
        // discover the problem at the payment screen.
        const unresolved = [];
        for (const line of validLines) {
            const product = await this._ensureProductLoaded(line.productId);
            if (!product) {
                unresolved.push(line.productName || `#${line.productId}`);
            }
        }
        if (unresolved.length > 0) {
            this.state.errorMessage =
                `These raw materials could not be loaded and cannot be saved: ` +
                `${unresolved.join(", ")}. Please remove them and pick a different product.`;
            return;
        }

        const totalQty = this._getConvertedTotal(validLines);
        // totalQty is null when the units are not convertible: comparing
        // kilos of meat against a count of burgers has no correct answer,
        // so the check is skipped rather than guessed at.
        //
        // More than the product quantity is blocked: the Manufacturing
        // Order would pull more stock than it produces. Less is blocked
        // too for Mandatory products; for the others it is warned once,
        // and the next Confirm saves anyway, since trim, bone and cooking
        // loss can make a lower total correct.
        const tolerance = this.pos.config.raw_material_tolerance || 0;
        const check = compareRawMaterialTotal(totalQty, this.props.productQty, tolerance);
        const uomName = this.pos.models["uom.uom"]?.get(this.props.productUomId)?.name || "";
        const total = `${totalQty} ${uomName}`.trim();
        const expected = `${this.props.productQty} ${uomName}`.trim();

        if (check === "over") {
            this.state.warningMessage = "";
            this.state.errorMessage =
                `Total raw material quantity (${total}) cannot exceed the product quantity (${expected}) by more than ${tolerance}.`;
            return;
        }
        if (check === "under" && this.props.enforcement === "force") {
            this.state.warningMessage = "";
            this.state.errorMessage =
                `Total raw material quantity (${total}) is less than the product quantity (${expected}). ` +
                `This product requires the raw materials to add up to ${expected}.`;
            return;
        }
        if (check === "under" && !this.state.warningMessage) {
            this.state.warningMessage =
                `Total raw material quantity (${total}) is less than the product quantity (${expected}). ` +
                `The raw materials should add up to ${expected}. ` +
                `Correct the quantities, or press "Confirm anyway" to save as it is.`;
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