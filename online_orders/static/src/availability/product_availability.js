import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Annex 4A: Product Availability.
 * Published website products, name + one switch (Available / Out of stock).
 * A tap saves at once: the server writes the website ribbon, which the
 * website and the Meta catalog read.
 */
export class ProductAvailability extends Component {
    static template = "online_orders.ProductAvailability";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            products: [],
            search: "",
            filter: "all",
            saving: {},
            loaded: false,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.products = await this.orm.call("product.template", "online_availability_list", []);
        this.state.loaded = true;
    }

    /** Products matching the search (the filter counts follow the search). */
    get searched() {
        const term = this.state.search.trim().toLowerCase();
        if (!term) {
            return this.state.products;
        }
        return this.state.products.filter((p) => p.name.toLowerCase().includes(term));
    }

    get counts() {
        const searched = this.searched;
        const outOfStock = searched.filter((p) => p.out_of_stock).length;
        return { all: searched.length, available: searched.length - outOfStock, out_of_stock: outOfStock };
    }

    get filters() {
        const counts = this.counts;
        return [
            { key: "all", label: _t("All"), count: counts.all },
            { key: "available", label: _t("Available"), count: counts.available },
            { key: "out_of_stock", label: _t("Out of stock"), count: counts.out_of_stock },
        ];
    }

    get visible() {
        const filter = this.state.filter;
        return this.searched.filter(
            (p) =>
                filter === "all" ||
                (filter === "available" && !p.out_of_stock) ||
                (filter === "out_of_stock" && p.out_of_stock)
        );
    }

    setFilter(key) {
        this.state.filter = key;
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
    }

    /** One tap: the switch changes at once, then the server saves it. */
    async toggle(product) {
        if (this.state.saving[product.id]) {
            return;
        }
        const wasOutOfStock = product.out_of_stock;
        product.out_of_stock = !wasOutOfStock;
        this.state.saving[product.id] = true;
        try {
            const result = await this.orm.call("product.template", "online_set_availability", [
                product.id,
                wasOutOfStock,
            ]);
            product.out_of_stock = result.out_of_stock;
            this.notification.add(result.message, { type: "success" });
        } catch (error) {
            product.out_of_stock = wasOutOfStock;
            throw error;
        } finally {
            delete this.state.saving[product.id];
        }
    }
}

registry.category("actions").add("online_orders.product_availability", ProductAvailability);
