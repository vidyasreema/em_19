import { Component, onWillStart, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { kanbanView } from "@web/views/kanban/kanban_view";

/** Open / overdue / delivered today, refreshed whenever the board changes. */
export class OnlineOrdersCounters extends Component {
    static template = "online_orders.Counters";
    static props = { model: Object };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ open: 0, overdue: 0, delivered_today: 0 });
        onWillStart(() => this.load());
        useBus(this.props.model.bus, "update", () => this.load());
    }

    async load() {
        Object.assign(this.state, await this.orm.call("sale.order", "get_online_order_counters", []));
    }
}

export class OnlineOrdersKanbanController extends KanbanController {
    static components = { ...KanbanController.components, OnlineOrdersCounters };
}

/**
 * Moving a card asks for confirmation first. Dropping it on the Cancelled
 * column opens the cancellation dialog instead (a reason is required).
 * The server refuses the other forbidden moves (backwards, to Completed).
 */
export class OnlineOrdersKanbanRenderer extends KanbanRenderer {
    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
        onWillStart(async () => {
            const stages = await this.orm.searchRead("online.order.stage", [], ["code"]);
            this.stageCodes = Object.fromEntries(stages.map((s) => [s.id, s.code]));
        });
    }

    async sortRecordDrop(dataRecordId, dataGroupId, params) {
        const targetGroupId = params.parent?.dataset.id;
        const list = this.props.list;
        if (!list.isGrouped || !targetGroupId || targetGroupId === dataGroupId) {
            return super.sortRecordDrop(...arguments);
        }
        const targetGroup = list.groups.find((g) => g.id === targetGroupId);
        const sourceGroup = list.groups.find((g) => g.id === dataGroupId);
        const record = sourceGroup?.list.records.find((r) => r.id === dataRecordId);
        if (!targetGroup || !record) {
            return;
        }
        params.parent.classList.remove("o_kanban_hover");
        // Odoo only moves the card to a column marked as hovered; the mark is
        // gone while the dialog is open, so it is set again before moving.
        const moveCard = () => {
            params.parent.classList.add("o_kanban_hover");
            return super.sortRecordDrop(dataRecordId, dataGroupId, params);
        };

        if (this.stageCodes[targetGroup.value] === "cancelled") {
            await this.action.doAction("online_orders.action_online_order_cancel_wizard", {
                additionalContext: { default_order_id: record.resId },
                onClose: () => list.model.load(),
            });
            return;
        }
        const confirmed = await new Promise((resolve) => {
            this.dialog.add(
                ConfirmationDialog,
                {
                    title: _t("Move order"),
                    body: _t("Move %(order)s to %(stage)s?", {
                        order: record.data.name,
                        stage: targetGroup.displayName,
                    }),
                    confirm: () => resolve(true),
                    cancel: () => resolve(false),
                },
                { onClose: () => resolve(false) }
            );
        });
        if (confirmed) {
            return moveCard();
        }
    }
}

export const onlineOrdersKanbanView = {
    ...kanbanView,
    Controller: OnlineOrdersKanbanController,
    Renderer: OnlineOrdersKanbanRenderer,
    buttonTemplate: "online_orders.KanbanButtons",
};

registry.category("views").add("online_orders_kanban", onlineOrdersKanbanView);
