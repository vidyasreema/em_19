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
     * Price of one whole pack for this line's customer:
     * order's pricelist first, then the POS default pricelist. Null if none.
     */
    getPackPrice(uomId) {
        const defaultPricelist = this.models["pos.config"].getFirst()?.pricelist_id;
        const rule =
            this.getPackRule(this.order_id.pricelist_id, uomId) ||
            this.getPackRule(defaultPricelist, uomId);
        return rule && rule.compute_price === "fixed" ? rule.fixed_price : null;
    },

    /** How much of the base unit one pack of this line contains (e.g. 9 kg). */
    getQtyPerPack() {
        const pack = this.pack_uom_id;
        return pack ? pack.factor / this.product_id.product_tmpl_id.uom_id.factor : 0;
    },

    /** True if the line quantity is a whole number of packs (e.g. 18 kg = 2 cartons of 9 kg). */
    isWholePacks() {
        const qtyPerPack = this.getQtyPerPack();
        if (!qtyPerPack) {
            return false;
        }
        const packs = this.qty / qtyPerPack;
        return Math.abs(packs - Math.round(packs)) < 0.0001 && Math.round(packs) !== 0;
    },

    /** Number of packs on the line (0 if not a whole number of packs). */
    getPackCount() {
        return this.isWholePacks() ? Math.round(this.qty / this.getQtyPerPack()) : 0;
    },

    /** Price of one pack as currently on the line (unit price x pack size). */
    getPackUnitPrice() {
        return (this.getUnitPrice ? this.getUnitPrice() : this.price_unit) * this.getQtyPerPack();
    },

    /** Normal (loose) price for the current quantity, as Odoo would compute it. */
    setLoosePrice() {
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
    },

    /**
     * Sets the right price for a line that has a pack:
     * - whole number of packs: pack price
     * - not whole (e.g. while typing, or a loose amount): loose price
     * The pack link is kept, so typing 2 then 0 (= 20 kg) returns to the pack price.
     * Returns true only if a pack price was applied.
     */
    applyPackPrice() {
        const pack = this.pack_uom_id;
        if (!pack) {
            return false;
        }
        if (!this.isWholePacks()) {
            this.setLoosePrice();
            return false;
        }
        const packPrice = this.getPackPrice(pack.id);
        if (packPrice === null) {
            return false;
        }
        this.setUnitPrice(packPrice / this.getQtyPerPack());
        this.price_type = "manual";
        return true;
    },

    /** Turns a pack line back into a normal loose line (quantity unchanged). */
    removePack() {
        this.update({ pack_uom_id: false });
        this.setLoosePrice();
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

    /** Quantity change: for pack lines, choose pack or loose price for the new quantity. */
    setQuantity(quantity, keep_price) {
        const result = super.setQuantity(quantity, keep_price);
        if (this.pack_uom_id) {
            this.applyPackPrice();
        }
        return result;
    },
});