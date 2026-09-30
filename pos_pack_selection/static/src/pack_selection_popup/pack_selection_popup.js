import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class PackSelectionPopup extends Component {
    static template = "pos_pack_selection.PackSelectionPopup";
    static components = { Dialog };
    static props = {
        title: String,
        uomName: String,
        packs: Array, // [{ id, uomId, name, qty, priceText, isCurrent }]
        showLoose: { type: Boolean, optional: true },
        onSelect: Function,
        onLoose: { type: Function, optional: true },
        close: Function,
    };

    selectPack(pack) {
        this.props.onSelect(pack);
        this.props.close();
    }

    selectLoose() {
        this.props.onLoose?.();
        this.props.close();
    }
}