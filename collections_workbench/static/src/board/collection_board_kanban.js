import { onWillStart, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";

/**
 * Follow-up board (FR-21, FR-22, VR-12).
 *
 * - Tabs with counts: Approvals, Collection Follow-up, Payment Agreements,
 *   Blacklist, Legal Cases and any pipeline added in Settings.
 * - Dropping a card on another stage never writes the stage directly: the
 *   server decides. Stages with an email, a VIP approval or another pipeline
 *   open the "Follow up" dialog (nothing moves before confirmation); other
 *   stages move at once and are logged.
 */
export class CollectionBoardController extends KanbanController {
    static template = "collections_workbench.BoardView";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.boardTabs = [];
        onWillStart(async () => {
            this.boardTabs = await this.orm.call("collection.pipeline", "board_tabs", []);
        });
        // Customers not followed up yet sit in the empty-stage column, which
        // Odoo folds by default: open it, it is where the work starts (BR-12).
        this._unfoldedOnce = false;
        useEffect(
            () => {
                const groups = this.model.root.groups || [];
                const empty = groups.find((g) => !g.value && g.isFolded && g.count);
                if (empty && !this._unfoldedOnce) {
                    this._unfoldedOnce = true;
                    empty.toggle();
                }
            },
            () => [this.model.root.groups && this.model.root.groups.length]
        );
    }

    get activePipelineId() {
        return this.props.context.default_collection_pipeline_id;
    }

    async openBoardTab(tab) {
        let action = tab.action;
        if (tab.pipeline_id) {
            action = await this.orm.call("collection.pipeline", "action_open_board", [[tab.pipeline_id]]);
        }
        await this.actionService.doAction(action, { stackPosition: "replaceCurrentAction" });
    }
}

export class CollectionBoardRenderer extends KanbanRenderer {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
    }

    async sortRecordDrop(dataRecordId, dataGroupId, params) {
        const { parent } = params;
        const list = this.props.list;
        const targetGroupId = parent?.dataset.id;
        if (!list.isGrouped || !targetGroupId || targetGroupId === dataGroupId) {
            return super.sortRecordDrop(...arguments);
        }
        parent.classList.remove("o_kanban_hover");
        const targetGroup = list.groups.find((g) => g.id === targetGroupId);
        const sourceGroup = list.groups.find((g) => g.id === dataGroupId);
        const record = sourceGroup?.list.records.find((r) => r.id === dataRecordId);
        if (!targetGroup || !record) {
            return;
        }
        const reload = () => list.model.load();
        const action = await this.orm.call("res.partner", "collection_board_drop", [
            [record.resId],
            targetGroup.value || false,
        ]);
        if (action) {
            await this.actionService.doAction(action, { onClose: reload });
        } else {
            await reload();
        }
    }
}

registry.category("views").add("collection_board_kanban", {
    ...kanbanView,
    Controller: CollectionBoardController,
    Renderer: CollectionBoardRenderer,
});
