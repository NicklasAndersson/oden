"""
Template-related handlers for Oden web GUI.

Provides API endpoints for viewing, editing, and managing report templates.
"""

import io
import logging
import zipfile

from aiohttp import web

from oden.template_loader import (
    APPEND_TEMPLATE,
    REPORT_TEMPLATE,
    VALID_TEMPLATES,
    get_template_content,
    load_template_from_file,
    render_template_from_string,
    save_template_content,
    validate_template,
)

logger = logging.getLogger(__name__)

# Sample data for template preview
# Minimal data: only required fields
SAMPLE_DATA_MINIMAL = {
    "report": {
        "fileid": "061430-46701234567-Nicklas",
        "group_title": "7s-test",
        "group_id": "abc123xyz789",
        "tnr": "061430",
        "timestamp_iso": "2026-02-06T14:30:00+01:00",
        "sender_display": "Nicklas ([[+46701234567]])",
        "message": "Detta är ett testmeddelande.",
    },
    "append": {
        "tnr": "061445",
        "timestamp_iso": "2026-02-06T14:45:00+01:00",
        "sender_display": "Nicklas ([[+46701234567]])",
        "message": "Detta är ett tillägg till rapporten.",
    },
}

# Full data: all fields including optional ones
SAMPLE_DATA_FULL = {
    "report": {
        "fileid": "061430-46701234567-Nicklas",
        "group_title": "7s-test",
        "group_id": "abc123xyz789",
        "tnr": "061430",
        "timestamp_iso": "2026-02-06T14:30:00+01:00",
        "sender_display": "Nicklas ([[+46701234567]])",
        "sender_name": "Nicklas",
        "sender_number": "+46701234567",
        "lat": "59.3293",
        "lon": "18.0686",
        "quote_formatted": "> Tidigare meddelande från Erik:\n> Lägesrapport kl 14:00",
        "message": "Detta är ett testmeddelande med [[ABC123]] regnummer.",
        "attachments": ["![[bild_001.jpg]]", "![[dokument.pdf]]"],
    },
    "append": {
        "tnr": "061445",
        "timestamp_iso": "2026-02-06T14:45:00+01:00",
        "sender_display": "Nicklas ([[+46701234567]])",
        "message": "Detta är ett tillägg med [[XYZ789]] referens.",
        "attachments": ["![[tillägg_bild.jpg]]"],
    },
}

# Template variable descriptions for UI
TEMPLATE_VARIABLES = {
    "report": [
        {"name": "fileid", "required": True, "description": "Unikt fil-ID (DDHHMM-telefon-namn)"},
        {"name": "group_title", "required": True, "description": "Signal-gruppens namn"},
        {"name": "group_id", "required": True, "description": "Signal-gruppens ID"},
        {"name": "tnr", "required": True, "description": "Tidsstämpel i DDHHMM-format"},
        {"name": "timestamp_iso", "required": True, "description": "Full ISO 8601-tidsstämpel"},
        {"name": "sender_display", "required": True, "description": "Formaterad avsändarsträng"},
        {"name": "sender_name", "required": False, "description": "Avsändarens visningsnamn"},
        {"name": "sender_number", "required": False, "description": "Avsändarens telefonnummer"},
        {"name": "lat", "required": False, "description": "Latitud från Google Maps-länk"},
        {"name": "lon", "required": False, "description": "Longitud från Google Maps-länk"},
        {"name": "quote_formatted", "required": False, "description": "Förformaterat citat-block"},
        {"name": "message", "required": False, "description": "Meddelandetext med regex-länkar"},
        {"name": "attachments", "required": False, "description": "Lista med Obsidian-embed-länkar"},
    ],
    "append": [
        {"name": "tnr", "required": True, "description": "Tidsstämpel i DDHHMM-format"},
        {"name": "timestamp_iso", "required": True, "description": "Full ISO 8601-tidsstämpel"},
        {"name": "sender_display", "required": True, "description": "Formaterad avsändarsträng"},
        {"name": "message", "required": False, "description": "Meddelandetext med regex-länkar"},
        {"name": "attachments", "required": False, "description": "Lista med Obsidian-embed-länkar"},
    ],
}


def _get_template_key(template_name: str) -> str:
    """Convert template filename to key (report or append)."""
    if template_name == REPORT_TEMPLATE:
        return "report"
    elif template_name == APPEND_TEMPLATE:
        return "append"
    raise ValueError(f"Unknown template: {template_name}")


async def templates_list_handler(request: web.Request) -> web.Response:
    """List available templates with metadata."""
    templates = []
    for name in VALID_TEMPLATES:
        key = _get_template_key(name)
        templates.append(
            {
                "name": name,
                "key": key,
                "description": "Rapportmall för nya meddelanden" if key == "report" else "Mall för tillägg",
                "variables": TEMPLATE_VARIABLES.get(key, []),
            }
        )
    return web.json_response({"templates": templates})


async def template_get_handler(request: web.Request) -> web.Response:
    """Get template content by name."""
    name = request.match_info.get("name")

    if name not in VALID_TEMPLATES:
        return web.json_response(
            {"error": f"Okänd mall: {name}"},
            status=404,
        )

    try:
        content = get_template_content(name)
        key = _get_template_key(name)
        return web.json_response(
            {
                "name": name,
                "key": key,
                "content": content,
                "variables": TEMPLATE_VARIABLES.get(key, []),
            }
        )
    except Exception as e:
        logger.error(f"Error getting template {name}: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def template_save_handler(request: web.Request) -> web.Response:
    """Save template content."""
    name = request.match_info.get("name")

    if name not in VALID_TEMPLATES:
        return web.json_response(
            {"error": f"Okänd mall: {name}"},
            status=404,
        )

    try:
        data = await request.json()
        content = data.get("content", "")

        if not content.strip():
            return web.json_response(
                {"success": False, "error": "Mallinnehåll kan inte vara tomt"},
                status=400,
            )

        # Validate template syntax
        is_valid, error = validate_template(content)
        warning = None
        if not is_valid:
            warning = f"Varning: Mallsyntaxfel - {error}"
            logger.warning(f"Template {name} saved with syntax error: {error}")

        # Save template (even with syntax errors, as per requirements)
        if save_template_content(name, content):
            logger.info("Template '%s' saved successfully via web GUI", name)
            result = {
                "success": True,
                "message": "Mall sparad",
            }
            if warning:
                result["warning"] = warning
            return web.json_response(result)
        else:
            return web.json_response(
                {"success": False, "error": "Kunde inte spara mall"},
                status=500,
            )

    except Exception as e:
        logger.error(f"Error saving template {name}: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def template_preview_handler(request: web.Request) -> web.Response:
    """Preview template with sample data."""
    name = request.match_info.get("name")

    if name not in VALID_TEMPLATES:
        return web.json_response(
            {"error": f"Okänd mall: {name}"},
            status=404,
        )

    try:
        data = await request.json()
        content = data.get("content", "")
        use_full_data = data.get("full", False)

        if not content.strip():
            return web.json_response(
                {"error": "Mallinnehåll kan inte vara tomt"},
                status=400,
            )

        # Select sample data
        key = _get_template_key(name)
        sample_data = SAMPLE_DATA_FULL if use_full_data else SAMPLE_DATA_MINIMAL
        context = sample_data.get(key, {})

        # Ensure attachments is always a list for the template
        if "attachments" not in context:
            context["attachments"] = []

        # Validate syntax first
        is_valid, error = validate_template(content)
        if not is_valid:
            return web.json_response(
                {
                    "success": False,
                    "error": f"Mallsyntaxfel: {error}",
                    "preview": None,
                }
            )

        # Render preview
        try:
            preview = render_template_from_string(content, context)
            return web.json_response(
                {
                    "success": True,
                    "preview": preview,
                    "sample_data": context,
                }
            )
        except Exception as e:
            return web.json_response(
                {
                    "success": False,
                    "error": f"Renderingsfel: {e}",
                    "preview": None,
                }
            )

    except Exception as e:
        logger.error(f"Error previewing template {name}: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def template_reset_handler(request: web.Request) -> web.Response:
    """Reset template to default (from file)."""
    name = request.match_info.get("name")

    if name not in VALID_TEMPLATES:
        return web.json_response(
            {"error": f"Okänd mall: {name}"},
            status=404,
        )

    try:
        # Load default content from file
        default_content = load_template_from_file(name)

        # Save to database (overwrites custom content)
        if save_template_content(name, default_content):
            logger.info("Template '%s' reset to default via web GUI", name)
            return web.json_response(
                {
                    "success": True,
                    "message": "Mall återställd till standard",
                    "content": default_content,
                }
            )
        else:
            return web.json_response(
                {"success": False, "error": "Kunde inte återställa mall"},
                status=500,
            )

    except FileNotFoundError:
        return web.json_response(
            {"success": False, "error": "Standardmall hittades inte"},
            status=500,
        )
    except Exception as e:
        logger.error(f"Error resetting template {name}: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def template_export_handler(request: web.Request) -> web.Response:
    """Export single template as downloadable file."""
    name = request.match_info.get("name")

    if name not in VALID_TEMPLATES:
        return web.json_response(
            {"error": f"Okänd mall: {name}"},
            status=404,
        )

    try:
        content = get_template_content(name)
        return web.Response(
            text=content,
            content_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={name}"},
        )
    except Exception as e:
        logger.error(f"Error exporting template {name}: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def templates_export_all_handler(request: web.Request) -> web.Response:
    """Export all templates as a ZIP file."""
    try:
        # Create in-memory ZIP file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in VALID_TEMPLATES:
                content = get_template_content(name)
                zf.writestr(name, content)

        zip_buffer.seek(0)
        return web.Response(
            body=zip_buffer.read(),
            content_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=oden-templates.zip"},
        )
    except Exception as e:
        logger.error(f"Error exporting all templates: {e}")
        return web.json_response({"error": str(e)}, status=500)
