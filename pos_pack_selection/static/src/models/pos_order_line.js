import { patch } from "@web/core/utils/patch";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";

patch(PosOrderline.prototype, {
    /**
     * Finds the pack rule (Pack field = uomId) for this line's product in a pricelist.
     * Uses the patched findBestRule, which only accepts rules with a matching Pack.
     */
    getPackRule(pricelist, uomId) {
        if (!pricelist) {
            return null;
        }
        const rules = [
            ...(pricelist.getRulesByProductId(this.product_id.id) || []),
            ...(pricelist.getRulesByTmplId(this.product_id.product_tmpl_id.id) || []),
        ];
        return pricelist.findBestRule(rules, 0, uomId);
    },

    /**
     * True if the line quantity is a whole number of packs (e.g. 18 kg = 2 cartons of 9 kg).
     */
    isWholePacks() {
        const pack = this.pack_uom_id;
        if (!pack) {
            return false;
        }
        const qtyPerPack = pack.factor / this.product_id.product_tmpl_id.uom_id.factor;
        const packs = this.qty / qtyPerPack;
        return Math.abs(packs - Math.round(packs)) < 0.0001 && Math.round(packs) !== 0;
    },

    /**
     * Sets the right price for a line that has a pack:
     * - whole number of packs: pack price (customer's pricelist, else POS default pricelist)
     * - not whole (e.g. while typing, or a loose amount): normal loose price
     * The pack link is kept, so typing 2 then 0 (= 20 kg) returns to the pack price.
     * Returns true only if a pack price was applied.
     */
    applyPackPrice() {
        const pack = this.pack_uom_id;
        if (!pack) {
            return false;
        }
        if (!this.isWholePacks()) {
            this.price_type = "original";
            this.setUnitPrice(
                this.product_id.product_tmpl_id.getPrice(
                    this.order_id.pricelist_id,
                    this.getQuantity(),
                    this.getPriceExtra(),
                    false,
                    this.product_id
                )
            );
            return false;
        }
        const qtyPerPack = pack.factor / this.product_id.product_tmpl_id.uom_id.factor;
        const defaultPricelist = this.models["pos.config"].getFirst()?.pricelist_id;
        const rule =
            this.getPackRule(this.order_id.pricelist_id, pack.id) ||
            this.getPackRule(defaultPricelist, pack.id);

        if (rule && rule.compute_price === "fixed") {
            this.setUnitPrice(rule.fixed_price / qtyPerPack);
            this.price_type = "manual";
            return true;
        }
        return false;
    },

    /**
     * Barcode scan: Odoo sets the pack quantity from the packaging barcode.
     * We then save the pack on the line and apply the pack price.
     */
    setOptions(options) {
        super.setOptions(options);
        const code = options?.code?.code;
        if (!code) {
            return;
        }
        const packaging = this.models["product.uom"].getAllBy("barcode")[code];
        if (packaging && packaging.product_id?.id === this.product_id.id) {
            this.update({ pack_uom_id: packaging.uom_id });
            this.applyPackPrice();
        }
    },

    /**
     * Quantity change: for pack lines, choose pack or loose price for the new quantity.
     */
    setQuantity(quantity, keep_price) {
        const result = super.setQuantity(quantity, keep_price);
        if (this.pack_uom_id) {
            this.applyPackPrice();
        }
        return result;
    },
});