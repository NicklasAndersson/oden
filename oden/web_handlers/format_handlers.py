"""Rapportformat: report formats defined in the GUI (see oden/report_formats.py).

GET lists the formats with the branches that use them, and the built-in
formats as read-only entries with an editable starting point. PUT validates
and stores the whole list. POST …/test parses a pasted message with a (possibly
unsaved) format and shows the note it would write — nothing is written.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from oden import config as cfg
from oden.config_db import set_config_value
from oden.dry_run import build_test_message
from oden.report_formats import (
    STARTERS,
    FormatReportPipeline,
    load_formats,
    normalize_format,
    normalize_formats,
    parse,
    step_name,
)
from oden.routing import load_routing
from oden.web_handlers._helpers import handle_errors, parse_json_body

logger = logging.getLogger(__name__)

TEMPLATE_VARIABLES = {
    "fields": "Fälten, t.ex. {{ fields.till }}",
    "sections": "Avsnitten, t.ex. {{ sections.orientering }}",
    "other": "Rader före första avsnittet som inte är fält",
    "tnr": "TNR (filnamnet)",
    "id": "Anteckningens id (prefix + uuid), för frontmatter",
    "report_type": "Rapporttypen (typ: i frontmatter)",
    "report_time": "Rapportens tid (från TNR-fältet)",
    "report_time_iso": "Rapportens tid som 2026-09-24T14:30:00",
    "signal_time": "När meddelandet kom",
    "signal_time_iso": "När meddelandet kom, som 2026-09-24T14:30:00",
    "sender_name": "Avsändarens namn",
    "sender_number": "Avsändarens nummer",
    "sender_id": "Avsändarens id (Signal-uuid eller TAK-enhet)",
    "lat / lon": "Koordinater från första fältet av typen MGRS (tomma om inget)",
    "| yaml": "Filter: citerar ett värde för frontmatter, t.ex. {{ fields.till | yaml }}",
    "| plate": "Filter: registreringsnumret i kanonisk form (tomt om det inte är ett)",
    "| link_plates": "Filter: gör registreringsnummer i texten till [[länkar]]",
    "group": "Gruppen",
    "format": "Formatets namn",
    "message": "Hela meddelandet",
}


def _used_in(routing: dict[str, Any]) -> dict[str, list[str]]:
    """Format id → names of the branches whose steps include it."""
    used: dict[str, list[str]] = {}
    for branch in routing["branches"]:
        for step in branch.get("steps", []):
            if step["pipeline"].startswith("format:"):
                used.setdefault(step["pipeline"].removeprefix("format:"), []).append(branch["name"])
    return used


def _builtins() -> list[dict[str, Any]]:
    from oden.web_handlers.pipeline_handlers import _get_available_pipelines

    available = _get_available_pipelines()
    result = []
    for name, starter in STARTERS.items():
        meta = available.get(name, {})
        result.append(
            {
                "name": name,
                "display_name": meta.get("display_name", name),
                "selection_criteria": meta.get("selection_criteria", ""),
                "headers": starter["headers"],
                "starter": starter,
            }
        )
    return result


@handle_errors("report formats")
async def formats_handler(request: web.Request) -> web.Response:
    formats = load_formats(cfg)
    return web.json_response(
        {
            "formats": formats,
            "used_in": _used_in(load_routing(cfg)),
            "builtins": _builtins(),
            "template_variables": TEMPLATE_VARIABLES,
        }
    )


@handle_errors("save report formats")
@parse_json_body
async def formats_save_handler(request: web.Request) -> web.Response:
    try:
        formats = normalize_formats(request["json_body"].get("formats"))
    except ValueError as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=400)

    kept = {f["id"] for f in formats}
    existing = {f["id"] for f in load_formats(cfg)}
    for format_id, branches in _used_in(load_routing(cfg)).items():
        if format_id in existing and format_id not in kept:
            return web.json_response(
                {
                    "success": False,
                    "error": f"Formatet {format_id!r} används i {', '.join(branches)} – ta bort steget där först",
                },
                status=400,
            )

    set_config_value(cfg.CONFIG_DB, "report_formats", formats)
    cfg.REPORT_FORMATS = formats
    logger.info("Rapportformat sparade: %s", ", ".join(f["name"] for f in formats) or "inga")
    return web.json_response({"success": True, "formats": formats})


@handle_errors("test report format")
@parse_json_body
async def format_test_handler(request: web.Request) -> web.Response:
    body = request["json_body"]
    text = str(body.get("text") or "")
    if not text.strip():
        return web.json_response({"success": False, "error": "Klistra in ett meddelande att testa"}, status=400)
    if len(text) > 20000:
        return web.json_response({"success": False, "error": "Meddelandet är för långt"}, status=400)
    # A pasted CoT (<event …>) is first made into text the way TAK → text does
    # with "formulärets namn som rubrik", so a format for a new ATAK form can be
    # tried on the real thing. The form's field names come back too — before the
    # format is checked, since filling a new format from them is the point.
    converted, form = None, None
    if text.lstrip().startswith("<"):
        from oden.tak.cot import cot_to_inbound
        from oden.tak.listener import render_message

        cot = cot_to_inbound(text)
        if cot is None:
            return web.json_response(
                {"success": False, "error": "Kunde inte tolka CoT:en (behöver ett <event> med position)"}, status=400
            )
        converted = render_message(cot, {"unknown_forms": "form_header"})[0] or ""
        if cot.custom_report_name and cot.custom_report:
            form = {"name": cot.custom_report_name, "fields": list(cot.custom_report)}
        text = converted

    try:
        fmt = normalize_format(body.get("format"))
    except ValueError as exc:
        if converted is None:
            return web.json_response({"success": False, "error": str(exc)}, status=400)
        # The CoT itself was fine: show its text (and its fields to fill in).
        return web.json_response(
            {"success": True, "converted_text": converted, "form": form, "format_error": str(exc), "matched": False}
        )

    pipeline = FormatReportPipeline(fmt)
    msg = build_test_message(text, "group:Testruta")
    matched = pipeline.matches_message(text)
    preview = await pipeline.preview(msg)
    return web.json_response(
        {
            "success": True,
            "converted_text": converted,
            "form": form,
            "step": step_name(fmt["id"]),
            "matched": matched,
            "parsed": parse(fmt, text) if matched else None,
            "handled": bool(preview.get("handled")),
            "failed": bool(preview.get("failed")),
            "reason": preview.get("reason"),
            "content": preview.get("content"),
            "warnings": [
                w.get("message", str(w)) if isinstance(w, dict) else str(w) for w in preview.get("warnings") or []
            ],
        }
    )
