import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMoney } from "../workbench/workbench";

/**
 * On-screen monthly report (FR-39), as the simulation's "Report" page:
 * KPIs, summary by list, monthly trend and rate per assignee. The PDF and
 * the email use the same figures.
 */
export class CollectionReport extends Component {
    static template = "collections_workbench.Report";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.formatMoney = formatMoney;
        this.state = useState({ data: null });
        onWillStart(() => this.load(false));
    }

    async load(snapshotId) {
        this.state.data = await this.orm.call("collection.snapshot", "report_page_data", [snapshotId]);
    }

    selectSnapshot(ev) {
        return this.load(parseInt(ev.target.value));
    }

    pct(value) {
        return ((value || 0) * 100).toFixed(1) + " %";
    }

    barWidth(value, list) {
        const max = Math.max(...list.map((x) => x.rate), 0.01);
        return Math.max(1, Math.round((value / max) * 100)) + "%";
    }

    get kpis() {
        const live = this.state.data.live;
        return [
            { label: "Due at snapshot", value: formatMoney(live.open) },
            { label: "Collected", value: formatMoney(live.collected) },
            { label: "Updated balance", value: formatMoney(live.balance) },
            { label: "Rate: all customers", value: this.pct(live.rate) },
            { label: "Rate: excl. agreements", value: this.pct(live.rate_ex_agreements) },
            { label: "Rate: net amount", value: this.pct(live.rate_net), help: "Excluding blacklist, court cases and agreements" },
            { label: "Paid / partly / not paid", value: `${live.paid} / ${live.partly} / ${live.not_paid}` },
            {
                label: "Avg days to close",
                value: live.avg_days === false ? "—" : `${live.avg_days} days`,
                help: `${live.cycles} closed cycles`,
            },
        ];
    }

    async downloadPdf() {
        await this.action.doAction("collections_workbench.action_report_monthly", {
            additionalContext: {
                active_model: "collection.snapshot",
                active_id: this.state.data.snapshot_id,
                active_ids: [this.state.data.snapshot_id],
            },
        });
    }

    async emailReport() {
        const action = await this.orm.call("collection.snapshot", "action_email_report", [
            [this.state.data.snapshot_id],
        ]);
        await this.action.doAction(action);
    }
}

registry.category("actions").add("collection_report", CollectionReport);
