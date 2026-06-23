"""Message observability and reprocess handlers for Oden 3.0."""

from __future__ import annotations

from aiohttp import web

from oden import config as cfg
from oden.app_state import get_app_state
from oden.messages_db import get_message_detail, get_message_stats, list_messages
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.pipelines_db import get_events_for_run, get_runs_for_message
from oden.web_handlers._helpers import handle_errors, require_writer

_orchestrator: PipelineOrchestrator | None = None


def _get_orchestrator() -> PipelineOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator(cfg.CONFIG_DB)
    return _orchestrator


def _get_int_query(request: web.Request, key: str, default: int, minimum: int, maximum: int) -> int:
    value_raw = request.query.get(key)
    if value_raw is None:
        return default
    try:
        value = int(value_raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


@handle_errors("list messages")
async def messages_list_handler(request: web.Request) -> web.Response:
    """List stored raw messages with simple filtering and pagination."""
    limit = _get_int_query(request, "limit", 50, 1, 500)
    offset = _get_int_query(request, "offset", 0, 0, 100000)

    account = request.query.get("account") or None
    status = request.query.get("status") or None
    group_id = request.query.get("group_id") or None

    messages = list_messages(
        cfg.CONFIG_DB,
        account=account,
        status=status,
        group_id=group_id,
        limit=limit,
        offset=offset,
    )

    return web.json_response(
        {
            "messages": messages,
            "limit": limit,
            "offset": offset,
            "count": len(messages),
        }
    )


@handle_errors("message detail")
async def message_detail_handler(request: web.Request) -> web.Response:
    """Return message detail with pipeline runs and run events."""
    message_id = int(request.match_info["id"])

    detail = get_message_detail(cfg.CONFIG_DB, message_id)
    if detail is None:
        return web.json_response({"success": False, "error": "Meddelande hittades inte"}, status=404)

    runs = get_runs_for_message(cfg.CONFIG_DB, message_id)
    for run in runs:
        run["events"] = get_events_for_run(cfg.CONFIG_DB, run["id"])

    return web.json_response({"message": detail, "runs": runs})


@handle_errors("message stats")
async def message_stats_handler(request: web.Request) -> web.Response:
    """Return aggregate message counters by status."""
    account = request.query.get("account") or None
    stats = get_message_stats(cfg.CONFIG_DB, account=account)
    return web.json_response(stats)


@handle_errors("reprocess message")
@require_writer
async def message_reprocess_handler(request: web.Request) -> web.Response:
    """Re-run pipelines for a stored message id."""
    message_id = int(request.match_info["id"])

    app_state = get_app_state()
    if app_state.reader is None or app_state.writer is None:
        return web.json_response({"success": False, "error": "Inte ansluten till signal-cli"}, status=503)

    did_run = await _get_orchestrator().reprocess(
        message_id=message_id,
        reader=app_state.reader,
        writer=app_state.writer,
    )

    if not did_run:
        return web.json_response({"success": False, "error": "Meddelande hittades inte"}, status=404)

    return web.json_response({"success": True, "message": "Meddelandet processades om"})
