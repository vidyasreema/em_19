import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class PackSelectionPopup extends Component {
    static template = "pos_pack_selection.PackSelectionPopup";
    static components = { Dialog };
    static props = {
        title: String,
        uomName: String,
        packs: Array,
        onSelect: Function,
        close: Function,
    };

    selectPack(pack) {
        this.props.onSelect(pack);
        this.props.close();
    }
}