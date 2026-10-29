import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { checkFileSize } from "@web/core/utils/files";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { ensureLineSaved, errorMessage, isLineReadonly } from "./utils";

async function uploadPhotos(http, notification, resModel, resId, files) {
    files = [...files].filter((file) => checkFileSize(file.size, notification));
    if (!files.length) {
        return false;
    }
    const response = await http.post(
        "/web/binary/upload_attachment",
        { csrf_token: odoo.csrf_token, ufile: files, model: resModel, id: resId },
        "text"
    );
    const result = JSON.parse(response);
    if (result.error) {
        notification.add(result.error, { type: "danger" });
        return false;
    }
    return true;
}

function pickFiles(withCamera, onFiles) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.multiple = !withCamera;
    if (withCamera) {
        // Opens the device rear camera directly on phone and tablet
        input.setAttribute("capture", "environment");
    }
    input.onchange = () => onFiles(input.files);
    input.click();
}

/** Photos of a line: labels, damage, condition of goods. */
export class CartonPhotosDialog extends Component {
    static template = "stock_barcode_register.CartonPhotosDialog";
    static components = { Dialog };
    static props = {
        resModel: String,
        resId: Number,
        title: String,
        readonly: { type: Boolean, optional: true },
        onChanged: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.http = useService("http");
        this.notification = useService("notification");
        this.state = useState({ photos: [] });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.photos = await this.orm.searchRead(
            "ir.attachment",
            [["res_model", "=", this.props.resModel], ["res_id", "=", this.props.resId], ["mimetype", "=like", "image/%"]],
            ["name", "create_date"],
            { order: "id" }
        );
    }

    add(withCamera) {
        pickFiles(withCamera, async (files) => {
            if (await uploadPhotos(this.http, this.notification, this.props.resModel, this.props.resId, files)) {
                await this.load();
                await this.props.onChanged();
            }
        });
    }

    async remove(photo) {
        try {
            await this.orm.unlink("ir.attachment", [photo.id]);
        } catch (error) {
            this.notification.add(errorMessage(error), { type: "danger" });
        }
        await this.load();
        await this.props.onChanged();
    }
}

export class CartonPhotos extends Component {
    static template = "stock_barcode_register.CartonPhotos";
    static props = { ...standardWidgetProps };

    setup() {
        this.http = useService("http");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
    }

    get count() {
        return this.props.record.data.photo_count || 0;
    }

    async takePhoto(ev) {
        ev.stopPropagation();
        const record = this.props.record;
        if (isLineReadonly(record)) {
            return this.openPhotos(ev);
        }
        const lineId = await ensureLineSaved(record, this.notification);
        if (!lineId) {
            return;
        }
        pickFiles(true, async (files) => {
            if (await uploadPhotos(this.http, this.notification, record.resModel, lineId, files)) {
                this.notification.add(_t("Photo added."), { type: "success" });
                await record.model.root.load();
            }
        });
    }

    async openPhotos(ev) {
        ev.stopPropagation();
        const record = this.props.record;
        const lineId = await ensureLineSaved(record, this.notification);
        if (!lineId) {
            return;
        }
        this.dialog.add(CartonPhotosDialog, {
            resModel: record.resModel,
            resId: lineId,
            title: _t("Photos: %s", record.data.product_id.display_name),
            readonly: isLineReadonly(record),
            onChanged: () => record.model.root.load(),
        });
    }
}

registry.category("view_widgets").add("carton_photos", {
    component: CartonPhotos,
});
