import mimetypes
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import Response, request


OFFICE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".dot",
    ".dotx",
    ".odt",
    ".rtf",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".ods",
    ".ppt",
    ".pptx",
    ".pptm",
    ".odp",
}

OFFICE_MIMETYPES = {
    "application/msword",
    "application/rtf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

IMAGE_EXTENSIONS = {".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"}
TEXT_EXTENSIONS = {".csv", ".css", ".htm", ".html", ".ini", ".js", ".json", ".log", ".md", ".sql", ".txt", ".xml", ".yaml", ".yml"}
MEDIA_EXTENSIONS = {".m4a", ".mkv", ".mp3", ".mp4", ".ogg", ".wav", ".webm"}


def _safe_filename(filename):
    filename = os.path.basename((filename or "Document").replace("\x00", ""))
    filename = filename.replace("\r", "_").replace("\n", "_").strip(" .")
    return filename[:255] or "Document"


def _office_converter():
    return shutil.which("libreoffice") or shutil.which("soffice") or shutil.which("soffice.exe")


def _viewer_kind(filename, mimetype):
    extension = os.path.splitext(filename or "")[1].lower()
    mimetype = (mimetype or "").lower()
    if extension in OFFICE_EXTENSIONS or mimetype in OFFICE_MIMETYPES:
        return "office"
    if extension == ".pdf" or mimetype.startswith("application/pdf"):
        return "pdf"
    if extension in IMAGE_EXTENSIONS or mimetype.startswith("image/"):
        return "image"
    if extension in TEXT_EXTENSIONS or mimetype.startswith("text/") or mimetype in {
        "application/javascript",
        "application/json",
        "application/xml",
    }:
        return "text"
    if extension in MEDIA_EXTENSIONS or mimetype.startswith(("audio/", "video/")):
        return "media"
    return "unsupported"


class UniversalDocumentPreviewController(http.Controller):

    def _get_stream(self, model, res_id, field, download_name):
        if not model or not field or not res_id:
            raise UserError(_("The document record is incomplete."))
        record = request.env["ir.binary"]._find_record(
            res_model=model,
            res_id=int(res_id),
            field=field,
        )
        filename = _safe_filename(download_name) if download_name else None
        return request.env["ir.binary"]._get_stream_from(
            record,
            field_name=field,
            filename=filename,
        )

    @http.route(
        "/universal_document_preview/info",
        type="jsonrpc",
        auth="user",
        readonly=True,
    )
    def preview_info(self, model, res_id, field, download_name=None):
        stream = self._get_stream(model, res_id, field, download_name)
        filename = _safe_filename(download_name or stream.download_name)
        mimetype = stream.mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        kind = _viewer_kind(filename, mimetype)
        download_url = f"/web/content/{model}/{int(res_id)}/{field}?" + urlencode(
            {"filename": filename, "download": "true"}
        )

        if kind == "office" and not _office_converter():
            return {
                "is_viewable": False,
                "name": filename,
                "download_url": download_url,
                "reason": _("LibreOffice is not installed on the Odoo server. You can still download this file."),
            }
        if kind == "unsupported":
            return {
                "is_viewable": False,
                "name": filename,
                "download_url": download_url,
                "reason": _("This file format has no configured preview renderer. You can still download it."),
            }

        base_params = {
            "model": model,
            "res_id": int(res_id),
            "field": field,
            "download_name": filename,
        }
        if kind == "office":
            source_url = "/universal_document_preview/office?" + urlencode(base_params)
            preview_kind = "pdf"
            preview_mimetype = "application/pdf"
        elif kind == "text":
            source_url = "/universal_document_preview/text?" + urlencode(base_params)
            preview_kind = kind
            preview_mimetype = "text/plain"
        else:
            source_url = f"/web/content/{model}/{int(res_id)}/{field}?" + urlencode({"filename": filename})
            preview_kind = kind
            preview_mimetype = mimetype

        return {
            "is_viewable": True,
            "name": filename,
            "kind": preview_kind,
            "mimetype": preview_mimetype,
            "source_url": source_url,
            "download_url": download_url,
        }

    @http.route(
        "/universal_document_preview/text",
        type="http",
        auth="user",
        methods=["GET"],
        readonly=True,
    )
    def preview_text(self, model, res_id, field, download_name=None, **_kwargs):
        stream = self._get_stream(model, res_id, field, download_name)
        filename = _safe_filename(download_name or stream.download_name)
        if _viewer_kind(filename, stream.mimetype) != "text":
            raise request.not_found()

        max_size_mb = int(
            request.env["ir.config_parameter"].sudo().get_param(
                "universal_document_preview.max_text_size_mb",
                "20",
            )
        )
        if stream.size and stream.size > max_size_mb * 1024 * 1024:
            return Response(
                _("This text document is too large to preview. The configured limit is %s MB.", max_size_mb),
                status=413,
                content_type="text/plain; charset=utf-8",
            )

        if stream.type == "data":
            text_data = stream.data
        elif stream.type == "path":
            with open(stream.path, "rb") as text_file:
                text_data = text_file.read()
        else:
            return Response(
                _("Cloud-hosted text streams cannot be rendered by this preview service."),
                status=415,
                content_type="text/plain; charset=utf-8",
            )

        response = Response(text_data, content_type="text/plain; charset=utf-8")
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @http.route(
        "/universal_document_preview/office",
        type="http",
        auth="user",
        methods=["GET"],
        readonly=True,
    )
    def preview_office(self, model, res_id, field, download_name=None, **_kwargs):
        converter = _office_converter()
        if not converter:
            raise request.not_found()

        stream = self._get_stream(model, res_id, field, download_name)
        filename = _safe_filename(download_name or stream.download_name)
        extension = os.path.splitext(filename)[1].lower()
        if extension not in OFFICE_EXTENSIONS:
            raise request.not_found()

        max_size_mb = int(
            request.env["ir.config_parameter"].sudo().get_param(
                "universal_document_preview.max_office_size_mb",
                "100",
            )
        )
        if stream.size and stream.size > max_size_mb * 1024 * 1024:
            return Response(
                _("This document is too large to preview. The configured limit is %s MB.", max_size_mb),
                status=413,
                content_type="text/plain; charset=utf-8",
            )

        with tempfile.TemporaryDirectory(prefix="odoo_document_preview_") as temp_dir:
            input_path = os.path.join(temp_dir, "source" + extension)
            if stream.type == "data":
                with open(input_path, "wb") as input_file:
                    input_file.write(stream.data)
            elif stream.type == "path":
                shutil.copyfile(stream.path, input_path)
            else:
                return Response(
                    _("Cloud-hosted document streams cannot be converted by this preview service."),
                    status=415,
                    content_type="text/plain; charset=utf-8",
                )

            try:
                result = subprocess.run(
                    [
                        converter,
                        "--headless",
                        "--nologo",
                        "--nodefault",
                        "--nolockcheck",
                        f"-env:UserInstallation={Path(temp_dir, 'libreoffice_profile').as_uri()}",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        temp_dir,
                        input_path,
                    ],
                    check=False,
                    capture_output=True,
                    timeout=300,
                )
            except (OSError, subprocess.TimeoutExpired):
                return Response(
                    _("The office document preview conversion timed out or could not start."),
                    status=500,
                    content_type="text/plain; charset=utf-8",
                )

            output_path = os.path.join(temp_dir, "source.pdf")
            if result.returncode or not os.path.isfile(output_path):
                return Response(
                    _("LibreOffice could not convert this document to PDF."),
                    status=422,
                    content_type="text/plain; charset=utf-8",
                )
            with open(output_path, "rb") as output_file:
                pdf_data = output_file.read()

        response = Response(pdf_data, content_type="application/pdf")
        response.headers["Content-Disposition"] = 'inline; filename="preview.pdf"'
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
