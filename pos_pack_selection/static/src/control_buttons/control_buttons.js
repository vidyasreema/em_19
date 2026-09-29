import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { PackSelectionPopup } from "../pack_selection_popup/pack_selection_popup";

patch(ControlButtons.prototype, {
    getProductPacks(product) {
        const baseUom = product.product_tmpl_id.uom_id;
        return this.pos.models["product.uom"]
            .filter((pack) => pack.product_id?.id === product.id && pack.uom_id)
            .map((pack) => ({
                id: pack.id,
                uomId: pack.uom_id.id,
                name: pack.uom_id.name,
                qty: pack.uom_id.factor / baseUom.factor,
            }));
    },

    onClickPackSelection() {
        const line = this.pos.getOrder()?.getSelectedOrderline();
        if (!line) {
            this.notification.add(_t("Select a product line first."), { type: "warning" });
            return;
        }
        const product = line.getProduct();
        const packs = this.getProductPacks(product);
        if (!packs.length) {
            this.notification.add(_t("This product has no pack sizes."), { type: "warning" });
            return;
        }
        this.dialog.add(PackSelectionPopup, {
            title: _t("Select pack: %s", product.display_name),
            uomName: product.product_tmpl_id.uom_id.name,
            packs,
            onSelect: (pack) => this.applyPackToLine(line, pack),
        });
    },

    applyPackToLine(line, pack) {
        line.setQuantity(pack.qty);
        line.update({ pack_uom_id: this.pos.models["uom.uom"].get(pack.uomId) });
        if (!line.applyPackPrice()) {
            this.notification.add(_t("No pack price found. Normal price is used."), {
                type: "warning",
            });
        }
    },
});