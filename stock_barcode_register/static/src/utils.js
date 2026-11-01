import { _t } from "@web/core/l10n/translation";

/** Line models carrying cartons, and their carton model. */
export const CARTON_CONFIG = {
    "stock.move": { resModel: "stock.move.carton", parentField: "move_id" },
    "stock.count.line": { resModel: "stock.count.carton", parentField: "line_id" },
};

/**
 * Save the form so the line has an id, and return it (false when it cannot be saved yet).
 */
export async function ensureLineSaved(record, notification) {
    if (!record.data.product_id) {
        notification.add(_t("Choose a product first."), { type: "warning" });
        return false;
    }
    const root = record.model.root;
    if (root.isDirty || !record.resId) {
        const saved = await root.save();
        if (!saved) {
            return false;
        }
    }
    if (!record.resId) {
        notification.add(_t("The line was saved. Click the button again."), { type: "info" });
        return false;
    }
    return record.resId;
}

export function isLineReadonly(record) {
    const rootState = record.model.root.data.state;
    if (record.resModel === "stock.count.line") {
        return rootState !== "draft";
    }
    return ["done", "cancel"].includes(rootState);
}

export function errorMessage(error) {
    return error?.data?.message || error?.message || String(error);
}
