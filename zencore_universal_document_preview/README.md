# Zencore Universal Document Preview (Odoo 19)

Install this addon once to add a Preview action to saved standard Binary fields across the Odoo backend. It does not add model-specific fields, tabs, or document tables.

## Supported previews

- Native: PDF, common images, text/CSV/XML/JSON, audio, and video.
- Converted through LibreOffice: DOC/DOCX/ODT/RTF, XLS/XLSX/ODS, and PPT/PPTX/ODP.
- Other formats keep their normal Download action.

## Office preview dependency

Install LibreOffice on the Odoo server and ensure `libreoffice`, `soffice`, or `soffice.exe` is available on the service user's `PATH`. Restart Odoo afterward.

The default Office preview limit is 100 MB. Change it with the system parameter:

```
universal_document_preview.max_office_size_mb
```

Text previews default to a 20 MB limit, configurable with:

```
universal_document_preview.max_text_size_mb
```

## Installation

1. Copy `zencore_universal_document_preview` into an Odoo addons path.
2. Restart Odoo and update the Apps list.
3. Install **Zencore Universal Document Preview**.
4. Hard-refresh the browser so the new backend assets are loaded.

For a newly uploaded file in an editable list, save the row/record before clicking Preview.

Version `19.0.1.0.5` contains no Product Template or Manufacturing Order document models/views. It provides the global Binary preview patch and the preview-enabled `list.binary` renderer without modifying Odoo's core ListRenderer behavior.

Version `19.0.1.0.6` preserves Odoo's standard Binary download behavior. Files download with the original uploaded filename supplied by the Binary field's `filename` attribute; no custom download-name override is applied.

Version `19.0.1.0.7` makes the list-view Download button use the same server-resolved download URL as the preview viewer, preventing a displayed Binary size (for example, `537.02 Kb`) from being used as the downloaded filename.
