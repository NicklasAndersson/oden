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
    "report_time": "Rapportens tid (från TNR-fältet)",
    "signal_time": "När meddelandet kom",
    "sender_name": "Avsändarens namn",
    "sender_number": "Avsändarens nummer",
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
    try:
        fmt = normalize_format(body.get("format"))
    except ValueError as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=400)

    pipeline = FormatReportPipeline(fmt)
    msg = build_test_message(text, f"group:{str(body.get('group') or 'Testruta')[:60]}")
    matched = pipeline.matches_message(text)
    preview = await pipeline.preview(msg)
    return web.json_response(
        {
            "success": True,
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
