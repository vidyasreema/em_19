import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMoney } from "../workbench/workbench";

/**
 * Collections dashboard (FR-38, AC-28): each card says in plain words what to do
 * today; every number opens the Collections table already filtered.
 */
export class CollectionDashboard extends Component {
    static template = "collections_workbench.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.formatMoney = formatMoney;
        this.state = useState({ data: null, scope: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("collection.snapshot.line", "dashboard_data", [this.state.scope]);
        this.state.scope = this.state.data.scope;
    }

    async setScope(scope) {
        this.state.scope = scope;
        await this.load();
    }

    async openCard(card) {
        if (!card.value) {
            return; // nothing to open
        }
        if (card.action === "approvals") {
            return this.action.doAction("collections_workbench.action_collection_approval");
        }
        // "My customers" only when the dashboard itself shows my customers
        const context = { ["search_default_" + card.filter]: 1 };
        if (this.state.scope === "mine") {
            context.search_default_my_customers = 1;
        }
        await this.action.doAction("collections_workbench.action_collection_snapshot_line", {
            additionalContext: context,
        });
    }

    async openLine(item) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "collection.snapshot.line",
            res_id: item.line_id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("collection_dashboard", CollectionDashboard);
