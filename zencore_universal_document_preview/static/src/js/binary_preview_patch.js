/** @odoo-module **/

import { rpc } from "@web/core/network/rpc";
import { download } from "@web/core/network/download";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import {
    BinaryField,
    ListBinaryField,
    listBinaryField,
} from "@web/views/fields/binary/binary_field";


patch(BinaryField.prototype, {
    setup() {
        super.setup();
        this.universalFileViewer = useFileViewer();
    },

    get canPreviewDocument() {
        return Boolean(
            this.props.record.resId &&
            this.props.record.data[this.props.name]
        );
    },

    get universalDownloadFileName() {
        return this.props.fileNameField ? this.fileName : "";
    },

    async getUniversalFileInfo() {
        if (!this.canPreviewDocument) {
            this.notification.add("Save the record before previewing or downloading the document.", {
                type: "warning",
            });
            return null;
        }

        try {
            return await rpc("/universal_document_preview/info", {
                model: this.props.record.resModel,
                res_id: this.props.record.resId,
                field: this.props.name,
                download_name: this.universalDownloadFileName,
            });
        } catch (_error) {
            this.notification.add("The document preview could not be prepared.", {
                type: "danger",
            });
            return null;
        }
    },

    async onUniversalFileDownload() {
        const info = await this.getUniversalFileInfo();
        if (info?.download_url) {
            await download({ data: {}, url: info.download_url });
        }
    },

    async onUniversalFilePreview() {
        const info = await this.getUniversalFileInfo();
        if (!info) {
            return;
        }

        if (!info.is_viewable) {
            this.notification.add(info.reason, {
                title: "Preview unavailable",
                type: "warning",
            });
            return;
        }

        let defaultSource = info.source_url;
        if (info.kind === "pdf") {
            defaultSource =
                `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(info.source_url)}` +
                "#pagemode=none";
        }
        const file = {
            name: info.name,
            mimetype: info.mimetype,
            defaultSource,
            downloadUrl: info.download_url,
            isImage: info.kind === "image",
            isPdf: info.kind === "pdf",
            isText: info.kind === "text",
            isVideo: info.kind === "media",
            isUrlYoutube: false,
            isViewable: true,
        };
        this.universalFileViewer.open(file);
    },
});


export class UniversalListBinaryPreviewField extends ListBinaryField {
    static template = "universal_document_preview.ListBinaryPreviewField";
}

const universalListBinaryPreviewField = {
    ...listBinaryField,
    component: UniversalListBinaryPreviewField,
};

registry.category("fields").add("universal_binary_preview", universalListBinaryPreviewField);
registry.category("fields").add("list.binary", universalListBinaryPreviewField, { force: true });
