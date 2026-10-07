import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { PackSelectionPopup } from "../pack_selection_popup/pack_selection_popup";

patch(ControlButtons.prototype, {
    formatPackPrice(amount) {
        if (amount === null) {
            return "—";
        }
        return this.env.utils?.formatCurrency
            ? this.env.utils.formatCurrency(amount)
            : amount.toFixed(2);
    },

    /**
     * Packs of the line's product = the product's Packagings (Sales tab),
     * with or without barcode, with each pack's price for the current customer.
     */
    getProductPacks(line) {
        const product = line.getProduct();
        const baseUom = product.product_tmpl_id.uom_id;
        return (product.product_tmpl_id.uom_ids || []).map((uom) => ({
            id: uom.id,
            uomId: uom.id,
            name: uom.name,
            qty: uom.factor / baseUom.factor,
            priceText: this.formatPackPrice(line.getPackPrice(uom.id)),
            isCurrent: line.pack_uom_id?.id === uom.id,
        }));
    },

    onClickPackSelection() {
        const line = this.pos.getOrder()?.getSelectedOrderline();
        if (!line) {
            this.notification.add(_t("Select a product line first."), { type: "warning" });
            return;
        }
        const product = line.getProduct();
        const packs = this.getProductPacks(line);
        if (!packs.length) {
            this.notification.add(_t("This product has no pack sizes."), { type: "warning" });
            return;
        }
        this.dialog.add(PackSelectionPopup, {
            title: _t("Select pack: %s", product.display_name),
            uomName: product.product_tmpl_id.uom_id.name,
            packs,
            showLoose: !!line.pack_uom_id,
            onSelect: (pack) => this.applyPackToLine(line, pack),
            onLoose: () => line.removePack(),
        });
    },

    /**
     * Converts the selected line into the chosen pack.
     * - Line is already this pack (whole packs): add one more pack.
     * - Otherwise (loose line or another pack): set it to exactly 1 pack.
     */
    applyPackToLine(line, pack) {
        const samePack = line.pack_uom_id?.id === pack.uomId && line.isWholePacks();
        const newQty = samePack ? line.getQuantity() + pack.qty : pack.qty;

        line.update({ pack_uom_id: this.pos.models["uom.uom"].get(pack.uomId) });
        line.setQuantity(newQty);
        if (!line.applyPackPrice()) {
            this.notification.add(_t("No pack price found. Normal price is used."), {
                type: "warning",
            });
        }
    },
});