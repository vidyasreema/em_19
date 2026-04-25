/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

class CommissionDashboard extends Component {
    static template = "sales_commission.CommissionDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            data: [],
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        const employeeId = this.props.record.resId;
        if (!employeeId) {
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "hr.employee",
                "action_get_commission_dashboard",
                [[employeeId]]
            );
            this.state.data = data;
        } catch (e) {
            console.error("Dashboard load error:", e);
            this.notification.add("Failed to load commission data.", { type: "danger" });
        }
        this.state.loading = false;
    }

    async refreshDashboard() {
        const employeeId = this.props.record.resId;
        if (!employeeId) return;
        this.state.loading = true;
        try {
            await this.orm.call(
                "hr.employee",
                "action_refresh_statements",
                [[employeeId]]
            );
            await this.loadData();
            this.notification.add("Dashboard refreshed successfully.", { type: "success" });
        } catch (e) {
            console.error("Refresh error:", e);
            this.notification.add(
                e.data?.message || "Error refreshing dashboard.",
                { type: "danger" }
            );
            this.state.loading = false;
        }
    }

    async generateStatement(monthDate, row) {
        if (row.paid || row.month_closed) {
            this.notification.add(
                "This statement is locked. It cannot be regenerated after payment.",
                { type: "warning" }
            );
            return;
        }

        const employeeId = this.props.record.resId;
        try {
            await this.orm.call(
                "hr.employee",
                "action_generate_statement",
                [[employeeId], monthDate]
            );
            this.notification.add("Statement generated successfully!", { type: "success" });
            await this.loadData();
        } catch (e) {
            this.notification.add(
                e.data?.message || "Error generating statement.",
                { type: "danger", sticky: true }
            );
        }
    }

    async payCommission(statementId, row) {
        if (row.paid || row.month_closed) {
            this.notification.add(
                "This statement is already paid and locked.",
                { type: "warning" }
            );
            return;
        }

        try {
            await this.orm.call(
                "commission.statement",
                "action_pay_commission",
                [[statementId]]
            );
            this.notification.add(
                "Commission paid! Journal entry created in DRAFT — please ask your accountant to post it.",
                { type: "success" }
            );
            await this.loadData();
        } catch (e) {
            this.notification.add(
                e.data?.message || "Error paying commission.",
                { type: "danger", sticky: true }
            );
        }
    }

    async openStatement(statementId, editable = false) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "commission.statement",
            res_id: statementId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
            context: {
                form_view_initial_mode: editable ? "edit" : "readonly",
            },
        });
        await this.loadData();
    }

    // ── NEW: Download PDF report via Odoo QWeb / wkhtmltopdf ──────────
    async downloadReport(statementId) {
        if (!statementId) {
            this.notification.add("No statement found to download.", { type: "warning" });
            return;
        }
        try {
            await this.action.doAction({
                type: "ir.actions.report",
                report_type: "qweb-pdf",
                report_name: "sales_commission.report_commission_statement",
                report_file: "sales_commission.report_commission_statement",
                context: {
                    active_ids: [statementId],
                    active_model: "commission.statement",
                },
            });
        } catch (e) {
            this.notification.add(
                e.data?.message || "Error generating PDF report.",
                { type: "danger", sticky: true }
            );
        }
    }

    formatAmount(amount, symbol) {
        return `${symbol} ${Number(amount).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}`;
    }

    getStatusInfo(row) {
        if (row.month_closed) {
            return { text: "Month Closed ✓", cls: "badge-closed" };
        }
        if (row.paid && row.journal_entry_state === "posted") {
            return { text: "Journal Posted", cls: "badge-closed" };
        }
        if (row.paid) {
            return { text: "Paid (Journal Draft)", cls: "badge-paid" };
        }
        if (row.eligible) {
            return { text: "Ready to Pay", cls: "badge-ready" };
        }
        if (row.target_achieved) {
            return { text: "Pending Collections", cls: "badge-pending" };
        }
        if (row.has_statement) {
            return { text: "Not Achieved", cls: "badge-not-achieved" };
        }
        return { text: "No Statement", cls: "badge-none" };
    }
}

registry.category("fields").add("commission_dashboard", {
    component: CommissionDashboard,
});