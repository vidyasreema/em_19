import { Component, markup, onWillStart, onWillUnmount, onWillUpdateProps, useState } from "@odoo/owl";
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { Domain } from "@web/core/domain";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";

const LINE_MODEL = "collection.snapshot.line";
const SECTION_ORDER = ["active", "court", "blacklist"];
const SECTION_LABELS = { active: "Active list", court: "Court case", blacklist: "Blacklist" };
const MISMATCHES = ["unrec", "missing", "nonote"];
const DEFAULT_WIDTHS = { partner: 260, note: 300, tags: 160 };

const numberFormat = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
});

export function formatMoney(value, blankZero = false) {
    if (!value && blankZero) {
        return "";
    }
    return numberFormat.format(value || 0);
}

/* ------------------------------------------------------------------ */
/* Side panel (FR-32..FR-36)                                            */
/* ------------------------------------------------------------------ */
export class WorkbenchPanel extends Component {
    static template = "collections_workbench.WorkbenchPanel";
    static components = { Chatter };
    static props = {
        lineId: Number,
        tab: String,
        setTab: Function,
        onClose: Function,
        onChanged: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ data: null, noteOffset: 0 });
        this.formatMoney = formatMoney;
        onWillStart(() => this.load(this.props.lineId));
        onWillUpdateProps((next) => {
            if (next.lineId !== this.props.lineId) {
                this.state.noteOffset = 0;
                return this.load(next.lineId);
            }
        });
    }

    async load(lineId, offset = this.state.noteOffset) {
        this.state.data = await this.orm.call(LINE_MODEL, "workbench_panel", [lineId, offset]);
    }

    markup(html) {
        return markup(html || "");
    }

    async loadOlder() {
        this.state.noteOffset += 5;
        await this.load(this.props.lineId);
    }

    async followUp(kind = "note") {
        const action = await this.orm.call("res.partner", "action_collection_followup", [
            [this.state.data.partner_id],
        ]);
        action.context = { ...action.context, default_kind: kind };
        await this.action.doAction(action, {
            onClose: async () => {
                await this.load(this.props.lineId);
                this.props.onChanged();
            },
        });
    }

    async openInvoices() {
        const action = await this.orm.call(LINE_MODEL, "workbench_open_invoices", [
            this.state.data.partner_id,
        ]);
        await this.action.doAction(action);
    }

    async statement(mode) {
        const action = await this.orm.call(LINE_MODEL, "workbench_statement", [
            this.state.data.partner_id,
            mode,
        ]);
        await this.action.doAction(action);
    }

    async openCard() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: this.state.data.partner_id,
            views: [[false, "form"]],
        });
    }

    async setAssignee(ev) {
        const employeeId = parseInt(ev.target.value) || false;
        await this.orm.call(LINE_MODEL, "workbench_set_assignee", [this.props.lineId, employeeId]);
        this.notification.add("Assignee updated: they were notified in their Inbox.", { type: "success" });
        await this.load(this.props.lineId);
        this.props.onChanged();
    }

    async moveBlacklist() {
        const action = await this.orm.call("res.partner", "action_collection_move_blacklist", [
            [this.state.data.partner_id],
        ]);
        await this.action.doAction(action, {
            onClose: async () => {
                await this.load(this.props.lineId);
                this.props.onChanged();
            },
        });
    }
}

/* ------------------------------------------------------------------ */
/* The table (FR-5..FR-16, FR-29..FR-31)                                */
/* ------------------------------------------------------------------ */
export class WorkbenchController extends Component {
    static template = "collections_workbench.Workbench";
    static components = { Layout, SearchBar, WorkbenchPanel };
    static props = ["*"];

    setup() {
        this.searchBarToggler = useSearchBarToggler();
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.formatMoney = formatMoney;
        this.SECTION_LABELS = SECTION_LABELS;
        this.state = useState({
            snapshots: [],
            latestId: false,
            generating: false,
            isAccountant: false,
            snapshotId: false,
            data: null,
            prefs: { widths: {}, hidden: [], shown: [], collapsed: {}, period_mode: "default" },
            sort: null,
            selected: {},
            panelOpen: false,
            panelTab: "customer",
            activeLineId: false,
            menu: null,
            menuSearch: "",
            menuPicked: {},
            menuMin: "",
            menuMax: "",
            showAdd: false,
            loading: true,
        });
        this.defs = null;
        this._onWindowClick = (ev) => {
            if (this.state.menu && !ev.target.closest(".o_cw_menu, .o_cw_th_label")) {
                this.state.menu = null;
            }
        };
        window.addEventListener("click", this._onWindowClick);
        onWillUnmount(() => window.removeEventListener("click", this._onWindowClick));

        onWillStart(async () => {
            const [snaps, defs, prefs] = await Promise.all([
                this.orm.call(LINE_MODEL, "workbench_snapshots", []),
                this.orm.call(LINE_MODEL, "workbench_columns", []),
                this.orm.call("collection.workbench.pref", "get_prefs", []),
            ]);
            this.defs = defs;
            Object.assign(this.state.prefs, prefs || {});
            this.applySnapshots(snaps);
            this.state.snapshotId = snaps.latest_id || (snaps.snapshots[0] && snaps.snapshots[0].id) || false;
            await this.load(this.props.domain);
        });
        onWillUpdateProps((next) => this.load(next.domain));
    }

    applySnapshots(snaps) {
        this.state.snapshots = snaps.snapshots;
        this.state.latestId = snaps.latest_id;
        this.state.generating = snaps.generating;
        this.state.isAccountant = snaps.is_accountant;
    }

    async load(domain = this.props.domain) {
        this.state.loading = true;
        if (!this.state.snapshotId) {
            this.state.data = null;
            this.state.loading = false;
            return;
        }
        this.state.data = await this.orm.call(LINE_MODEL, "workbench_data", [
            this.state.snapshotId,
            domain,
            this.state.prefs.period_mode || "default",
            this.state.prefs.period_breaks || [],
        ]);
        const ids = new Set(this.state.data.rows.map((r) => r.id));
        for (const id of Object.keys(this.state.selected)) {
            if (!ids.has(parseInt(id))) {
                delete this.state.selected[id];
            }
        }
        this.state.loading = false;
    }

    async refresh() {
        this.applySnapshots(await this.orm.call(LINE_MODEL, "workbench_snapshots", []));
        await this.load();
        this.notification.add("Live figures refreshed. The snapshot itself does not change.", {
            type: "info",
        });
    }

    /* ---------------- preferences ---------------- */
    savePrefs() {
        clearTimeout(this._saveTimer);
        this._saveTimer = setTimeout(() => {
            this.orm.call("collection.workbench.pref", "set_prefs", [{ ...this.state.prefs }]);
        }, 600);
    }

    async setPeriodMode(ev) {
        this.state.prefs.period_mode = ev.target.value;
        if (ev.target.value === "custom" && !(this.state.prefs.period_breaks || []).length) {
            // start from the current columns: one break at each column's first month
            this.state.prefs.period_breaks = this.state.data.periods.map((p) => p.months[0]).filter(Boolean);
        }
        this.savePrefs();
        await this.load();
    }

    /** Custom grouping (FR-6): a new column starts at each ticked month */
    isBreak(key) {
        return (this.state.prefs.period_breaks || []).includes(key);
    }

    async toggleBreak(key) {
        const breaks = new Set(this.state.prefs.period_breaks || []);
        if (breaks.has(key)) {
            breaks.delete(key);
        } else {
            breaks.add(key);
        }
        this.state.prefs.period_breaks = [...breaks].sort();
        this.savePrefs();
        await this.load();
    }

    resetWidths() {
        this.state.prefs.widths = {};
        this.savePrefs();
    }

    /* ---------------- snapshots (FR-2) ---------------- */
    async selectSnapshot(ev) {
        this.state.snapshotId = parseInt(ev.target.value);
        this.state.selected = {};
        await this.load();
    }

    async backToLatest() {
        this.state.snapshotId = this.state.latestId;
        await this.load();
    }

    get currentSnapshot() {
        return this.state.data && this.state.data.snapshot;
    }

    get isArchivedView() {
        const snap = this.currentSnapshot;
        return snap && (snap.state === "archived" || snap.id !== this.state.latestId);
    }

    /* ---------------- columns ---------------- */
    isVisible(def) {
        const prefs = this.state.prefs;
        if (def.locked) {
            return true;
        }
        if ((prefs.hidden || []).includes(def.key)) {
            return false;
        }
        if ((prefs.shown || []).includes(def.key)) {
            return true;
        }
        return def.visible;
    }

    get periodsVisible() {
        return !(this.state.prefs.hidden || []).includes("periods");
    }

    get columns() {
        if (!this.defs || !this.state.data) {
            return [];
        }
        const cols = [];
        const pushDef = (def) => {
            if (this.isVisible(def)) {
                cols.push({ ...def, width: this.state.prefs.widths[def.key] || DEFAULT_WIDTHS[def.key] || 130 });
            }
        };
        this.defs.columns.filter((c) => c.section === "customer").forEach(pushDef);
        if (this.periodsVisible) {
            for (const p of this.state.data.periods) {
                const key = "period:" + p.key;
                cols.push({
                    key,
                    label: p.label,
                    section: "periods",
                    type: "money",
                    locked: false,
                    filter: null,
                    periodKey: p.key,
                    kind: p.kind,
                    width: this.state.prefs.widths[key] || 110,
                });
            }
        }
        this.defs.columns.filter((c) => c.section !== "customer").forEach(pushDef);
        return cols;
    }

    get tableWidth() {
        return 34 + this.columns.reduce((sum, c) => sum + c.width, 0);
    }

    get sectionHeaders() {
        const headers = [];
        for (const col of this.columns) {
            const last = headers[headers.length - 1];
            if (last && last.key === col.section) {
                last.span++;
            } else {
                const def = this.defs.sections.find((s) => s.key === col.section);
                headers.push({ key: col.section, label: def.label, color: def.color, span: 1 });
            }
        }
        return headers;
    }

    sectionColor(sectionKey) {
        const def = this.defs.sections.find((s) => s.key === sectionKey);
        return def ? def.color : "";
    }

    get hiddenBySection() {
        if (!this.defs) {
            return [];
        }
        const groups = [];
        for (const section of this.defs.sections) {
            const items = this.defs.columns.filter((c) => c.section === section.key && !this.isVisible(c));
            if (section.key === "periods" && !this.periodsVisible) {
                items.push({ key: "periods", label: "All period columns" });
            }
            if (items.length) {
                groups.push({ section, items });
            }
        }
        return groups;
    }

    showColumn(key) {
        const prefs = this.state.prefs;
        prefs.hidden = (prefs.hidden || []).filter((k) => k !== key);
        if (!(prefs.shown || []).includes(key)) {
            prefs.shown = [...(prefs.shown || []), key];
        }
        this.savePrefs();
    }

    hideColumn(col) {
        if (col.locked) {
            return;
        }
        const key = col.section === "periods" ? "periods" : col.key;
        const prefs = this.state.prefs;
        prefs.shown = (prefs.shown || []).filter((k) => k !== key);
        prefs.hidden = [...new Set([...(prefs.hidden || []), key])];
        this.state.menu = null;
        this.savePrefs();
    }

    /* ---------------- column widths (FR-11) ---------------- */
    startResize(ev, col) {
        ev.preventDefault();
        ev.stopPropagation();
        const startX = ev.clientX;
        const startWidth = col.width;
        const onMove = (e) => {
            this.state.prefs.widths[col.key] = Math.max(50, startWidth + e.clientX - startX);
        };
        const onUp = () => {
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
            this.savePrefs();
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    }

    /* ---------------- values ---------------- */
    rawValue(col, row) {
        if (col.periodKey) {
            return row.periods[col.periodKey] || 0;
        }
        switch (col.type) {
            case "m2o":
                return row[col.key] ? row[col.key][1] : "";
            case "tags":
                return row.tags.map((t) => t.name).join(", ");
            case "note":
                return row.note ? row.note.category : "";
            default:
                return row[col.key];
        }
    }

    /** [value used in the domain, label] for header pick-lists */
    pickValues(col, row) {
        switch (col.key) {
            case "partner":
                return [[row.partner_id, row.partner]];
            case "salesman":
            case "assignee":
                return [row[col.key] ? [row[col.key][0], row[col.key][1]] : [false, "None"]];
            case "tags":
                return row.tags.length ? row.tags.map((t) => [t.id, t.name]) : [];
            case "pipeline":
            case "stage":
                return [[row[col.key] || false, row[col.key] || "None"]];
            case "live_status":
                return [[row.live_status, this.defs.status_labels[row.live_status]]];
            case "pay_check":
                return [[row.pay_check || false, row.pay_check ? this.defs.pay_check_labels[row.pay_check] : "None"]];
            case "note":
                return row.note ? [[row.note.category_id, row.note.category]] : [];
            case "pattern_label":
                return [[row.pattern, row.pattern_label]];
            case "deadline_label":
                return [[row.deadline_state, row.deadline_label]];
        }
        return [];
    }

    cellText(col, row) {
        const value = this.rawValue(col, row);
        if (col.type === "money") {
            return formatMoney(value, col.periodKey || col.key === "unreconciled_now");
        }
        if (col.key === "live_status") {
            return this.defs.status_labels[value] || "";
        }
        if (col.key === "pay_check") {
            return value ? this.defs.pay_check_labels[value] : "";
        }
        if (col.type === "int") {
            return value || "";
        }
        return value || "";
    }

    cellClass(col, row) {
        const classes = [];
        if (col.type === "money" || col.type === "int") {
            classes.push("text-end o_cw_num");
        }
        if (col.periodKey) {
            classes.push("o_cw_period o_cw_period_" + col.kind);
        }
        if (col.key === "unreconciled_now" && row.unreconciled_now > 0) {
            classes.push("o_cw_alert");
        }
        if (col.key === "pay_check" && MISMATCHES.includes(row.pay_check)) {
            classes.push("o_cw_alert");
        }
        if (col.key === "live_status") {
            classes.push("o_cw_status_" + row.live_status);
        }
        return classes.join(" ");
    }

    /* ---------------- rows, sections, totals (FR-13) ---------------- */
    get sortedRows() {
        const rows = [...((this.state.data && this.state.data.rows) || [])];
        const sort = this.state.sort;
        if (sort) {
            const col = this.columns.find((c) => c.key === sort.key);
            if (col) {
                rows.sort((a, b) => {
                    const va = this.rawValue(col, a);
                    const vb = this.rawValue(col, b);
                    const cmp = typeof va === "number" && typeof vb === "number"
                        ? va - vb
                        : String(va || "").localeCompare(String(vb || ""));
                    return sort.asc ? cmp : -cmp;
                });
            }
        }
        return rows;
    }

    get sections() {
        const rows = this.sortedRows;
        return SECTION_ORDER.map((key) => ({
            key,
            label: SECTION_LABELS[key],
            rows: rows.filter((r) => r.section === key),
            collapsed: !!this.state.prefs.collapsed[key],
        })).filter((s) => s.rows.length);
    }

    total(col, rows) {
        if (col.type !== "money") {
            return "";
        }
        return formatMoney(rows.reduce((sum, r) => sum + (this.rawValue(col, r) || 0), 0));
    }

    get allRows() {
        return (this.state.data && this.state.data.rows) || [];
    }

    toggleSection(key) {
        this.state.prefs.collapsed[key] = !this.state.prefs.collapsed[key];
        this.savePrefs();
    }

    /* ---------------- banners (FR-29, FR-31) ---------------- */
    get unreconciledRows() {
        return this.allRows.filter((r) => r.unreconciled_now > 0.005);
    }

    get unreconciledTotal() {
        return formatMoney(this.unreconciledRows.reduce((s, r) => s + r.unreconciled_now, 0));
    }

    get mismatchRows() {
        return this.allRows.filter((r) => MISMATCHES.includes(r.pay_check));
    }

    activatePredefinedFilter(name) {
        const searchModel = this.env.searchModel;
        const item = Object.values(searchModel.searchItems).find(
            (i) => i.type === "filter" && i.name === name
        );
        if (item && !searchModel.query.some((q) => q.searchItemId === item.id)) {
            searchModel.toggleSearchItem(item.id);
        }
    }

    /* ---------------- header menu: sort + filter (FR-10) ---------------- */
    openMenu(ev, col) {
        ev.stopPropagation();
        if (this.state.menu && this.state.menu.key === col.key) {
            this.state.menu = null;
            return;
        }
        const th = ev.currentTarget.closest("th");
        const root = th.closest(".o_cw_scroll");
        const rect = th.getBoundingClientRect();
        const rootRect = root.getBoundingClientRect();
        this.state.menuSearch = "";
        this.state.menuPicked = {};
        this.state.menuMin = "";
        this.state.menuMax = "";
        this.state.menu = {
            key: col.key,
            left: rect.left - rootRect.left + root.scrollLeft,
            top: rect.bottom - rootRect.top + root.scrollTop,
        };
    }

    get menuColumn() {
        return this.state.menu && this.columns.find((c) => c.key === this.state.menu.key);
    }

    get menuOptions() {
        const col = this.menuColumn;
        if (!col || col.filter !== "pick") {
            return [];
        }
        const seen = new Map();
        for (const row of this.allRows) {
            for (const [value, label] of this.pickValues(col, row)) {
                const k = JSON.stringify(value);
                if (!seen.has(k)) {
                    seen.set(k, { key: k, value, label: label || "None", count: 0 });
                }
                seen.get(k).count++;
            }
        }
        const search = this.state.menuSearch.toLowerCase();
        return [...seen.values()]
            .filter((o) => !search || String(o.label).toLowerCase().includes(search))
            .sort((a, b) => String(a.label).localeCompare(String(b.label)));
    }

    sortBy(asc) {
        this.state.sort = { key: this.state.menu.key, asc };
        this.state.menu = null;
    }

    togglePick(option) {
        if (this.state.menuPicked[option.key]) {
            delete this.state.menuPicked[option.key];
        } else {
            this.state.menuPicked[option.key] = option;
        }
    }

    applyFilter() {
        const col = this.menuColumn;
        let domain;
        let description;
        if (col.filter === "pick") {
            const picked = Object.values(this.state.menuPicked);
            if (!picked.length) {
                return;
            }
            const values = picked.map((p) => p.value).filter((v) => v !== false);
            const hasNone = picked.some((p) => p.value === false);
            const base = col.field.split(".")[0];
            const parts = [];
            if (values.length) {
                parts.push(new Domain([[col.field, "in", values]]));
            }
            if (hasNone) {
                parts.push(new Domain([[base, "=", false]]));
            }
            domain = Domain.or(parts).toString();
            description = `${col.label}: ${picked.map((p) => p.label).join(", ")}`;
        } else {
            const leaves = [];
            const labels = [];
            if (this.state.menuMin !== "") {
                leaves.push([col.field, ">=", parseFloat(this.state.menuMin)]);
                labels.push(`≥ ${this.state.menuMin}`);
            }
            if (this.state.menuMax !== "") {
                leaves.push([col.field, "<=", parseFloat(this.state.menuMax)]);
                labels.push(`≤ ${this.state.menuMax}`);
            }
            if (!leaves.length) {
                return;
            }
            domain = new Domain(leaves).toString();
            description = `${col.label} ${labels.join(" and ")}`;
        }
        this.state.menu = null;
        this.env.searchModel.createNewFilters([{ description, domain }]);
    }

    /* ---------------- selection + actions ---------------- */
    get selectedRows() {
        return this.allRows.filter((r) => this.state.selected[r.id]);
    }

    toggleSelect(row) {
        if (this.state.selected[row.id]) {
            delete this.state.selected[row.id];
        } else {
            this.state.selected[row.id] = true;
        }
    }

    toggleSelectAll(ev) {
        if (ev.target.checked) {
            for (const r of this.allRows) {
                this.state.selected[r.id] = true;
            }
        } else {
            this.state.selected = {};
        }
    }

    get allSelected() {
        return this.allRows.length && this.selectedRows.length === this.allRows.length;
    }

    async followUp(partnerIds, kind) {
        const action = await this.orm.call("res.partner", "action_collection_followup", [partnerIds]);
        if (kind) {
            action.context = { ...action.context, default_kind: kind };
        }
        await this.action.doAction(action, { onClose: () => this.load() });
    }

    followUpSelected() {
        const ids = [...new Set(this.selectedRows.map((r) => r.partner_id))];
        if (ids.length) {
            this.followUp(ids, "stage");
        }
    }

    async assignSelected() {
        const ids = this.selectedRows.map((r) => r.id);
        if (!ids.length) {
            return;
        }
        await this.action.doAction("collections_workbench.action_collection_assign_wizard", {
            additionalContext: { default_line_ids: ids },
            onClose: () => {
                this.state.selected = {};
                this.load();
            },
        });
    }

    async exportExcel() {
        const keys = this.columns.filter((c) => !c.periodKey).map((c) => c.key);
        if (this.periodsVisible) {
            keys.push("periods");
        }
        const url = await this.orm.call(LINE_MODEL, "workbench_export", [
            this.state.snapshotId,
            this.props.domain,
            this.state.prefs.period_mode || "default",
            keys,
            this.state.prefs.period_breaks || [],
        ]);
        window.location.href = url;
    }

    async statementPackage() {
        await this.action.doAction("collections_workbench.action_collection_package_wizard", {
            additionalContext: { default_snapshot_id: this.state.snapshotId },
        });
    }

    async newSnapshot() {
        await this.action.doAction("collections_workbench.action_collection_snapshot_wizard", {
            onClose: () => this.refresh(),
        });

    }

    /* ---------------- side panel ---------------- */
    togglePanel() {
        this.state.panelOpen = !this.state.panelOpen;
        if (this.state.panelOpen && !this.state.activeLineId && this.allRows.length) {
            this.state.activeLineId = this.allRows[0].id;
        }
    }

    onRowClick(ev, row) {
        if (ev.target.closest("button, input, a, select")) {
            return;
        }
        this.state.activeLineId = row.id;
    }

    openChat(ev, row) {
        ev.stopPropagation();
        this.state.activeLineId = row.id;
        this.state.panelTab = "discussion";
        this.state.panelOpen = true;
    }

    setPanelTab(tab) {
        this.state.panelTab = tab;
    }
}

export const workbenchView = {
    type: "list",
    display_name: "Collections",
    icon: "fa fa-table",
    multiRecord: true,
    searchMenuTypes: ["filter", "favorite"],
    Controller: WorkbenchController,
    props: (genericProps) => genericProps,
};

registry.category("views").add("collection_workbench", workbenchView);
