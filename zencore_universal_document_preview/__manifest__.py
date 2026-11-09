{
    "name": "Zencore Universal Document Preview",
    "summary": "Preview binary documents globally across the Odoo backend",
    "version": "19.0.1.0.8",
    "category": "Productivity/Documents",
    "author": "Mehedi Hasan",
    "website": "https://zencoreltd.com",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "zencore_universal_document_preview/static/src/js/binary_preview_patch.js",
            "zencore_universal_document_preview/static/src/xml/binary_preview.xml",
        ],
    },
    "installable": True,
    "application": False,
}
