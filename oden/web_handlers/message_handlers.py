"""Message observability and reprocess handlers for Oden 3.0."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from oden import config as cfg
from oden.app_state import get_app_state
from oden.flow_db import flow_summary, get_flow_item, list_flow
from oden.messages_db import get_message_detail, get_message_stats, list_messages
from oden.path_utils import is_within_directory, normalize_path
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.pipelines_db import get_events_for_run, get_runs_for_message
from oden.routing import branch_steps, load_routing
from oden.web_handlers._helpers import handle_errors, require_writer

_orchestrator: PipelineOrchestrator | None = None

# Enough for any report; a pasted log in a note is cut rather than shipped whole.
_OUTPUT_PREVIEW_MAX_BYTES = 20_000


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


def _get_bool_query(request: web.Request, key: str) -> bool:
    value_raw = request.query.get(key)
    if value_raw is None:
        return False
    return value_raw.strip().lower() in {"1", "true", "yes", "on"}


@handle_errors("list messages")
async def messages_list_handler(request: web.Request) -> web.Response:
    """List stored raw messages with simple filtering and pagination."""
    limit = _get_int_query(request, "limit", 50, 1, 500)
    offset = _get_int_query(request, "offset", 0, 0, 100000)

    account = request.query.get("account") or None
    status = request.query.get("status") or None
    group_id = request.query.get("group_id") or None
    has_content_only = _get_bool_query(request, "has_content")

    messages = list_messages(
        cfg.CONFIG_DB,
        account=account,
        status=status,
        group_id=group_id,
        has_content_only=has_content_only,
        limit=limit,
        offset=offset,
    )

    return web.json_response(
        {
            "messages": messages,
            "limit": limit,
            "offset": offset,
            "count": len(messages),
            "has_content_only": has_content_only,
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


_chain_orchestrator: PipelineOrchestrator | None = None


def _pipeline_chain() -> list[str]:
    """Pipeline names in the order the orchestrator runs them right now.

    Uses its own instance so reading the chain never creates (and pins) the
    shared orchestrator that reprocess uses.
    """
    global _chain_orchestrator
    try:
        if _chain_orchestrator is None:
            _chain_orchestrator = PipelineOrchestrator(cfg.CONFIG_DB)
        return [p.name for p in _chain_orchestrator._build_pipelines()]
    except Exception:
        return []


def _branch_names() -> list[dict[str, str]]:
    """``[{id, name}]`` of the branches, for the Flöde branch filter."""
    try:
        return [{"id": b["id"], "name": b["name"]} for b in load_routing(cfg)["branches"]]
    except Exception:
        return []


def _branch_chains() -> dict[str, list[str]]:
    """Branch id → the step names that run there now, for the "not run" markers in Flöde."""
    try:
        routing = load_routing(cfg)
        publish = _chain_orchestrator._publish_to_tak() if _chain_orchestrator else False
        return {b["id"]: [s["pipeline"] for s in branch_steps(b, publish_to_tak=publish)] for b in routing["branches"]}
    except Exception:
        return {}


def _read_output_preview(output_file: str | None) -> dict | None:
    """Read a written vault file for the detail view, only if it is inside the vault."""
    if not output_file or not cfg.VAULT_PATH:
        return None
    try:
        vault = normalize_path(cfg.VAULT_PATH)
        path = normalize_path(output_file)
    except (ValueError, OSError):
        return None
    if not is_within_directory(path, vault) or not path.is_file():
        return None
    with path.open("rb") as handle:
        data = handle.read(_OUTPUT_PREVIEW_MAX_BYTES + 1)
    return {
        "path": str(path.relative_to(vault)),
        "content": data[:_OUTPUT_PREVIEW_MAX_BYTES].decode("utf-8", errors="replace"),
        "truncated": len(data) > _OUTPUT_PREVIEW_MAX_BYTES,
    }


def _vault_relative(output_file: str | None) -> str | None:
    if not output_file or not cfg.VAULT_PATH:
        return output_file
    try:
        return str(Path(output_file).relative_to(Path(cfg.VAULT_PATH)))
    except ValueError:
        return output_file


def _relativize_steps(item: dict) -> None:
    for step in item.get("steps", []):
        step["output_path"] = _vault_relative(step.get("output_file"))
        step.pop("output_file", None)


@handle_errors("list flow")
async def flow_list_handler(request: web.Request) -> web.Response:
    """Everything that came in, newest first, with the route each message took."""
    limit = _get_int_query(request, "limit", 100, 1, 500)
    before_id = _get_int_query(request, "before_id", 0, 0, 2**62) or None
    include_empty = _get_bool_query(request, "include_empty")

    items = list_flow(
        cfg.CONFIG_DB,
        source=request.query.get("source") or None,
        status=request.query.get("status") or None,
        has_content_only=not include_empty,
        limit=limit,
        before_id=before_id,
        branch=request.query.get("branch") or None,
        pipeline=request.query.get("pipeline") or None,
        outcome=request.query.get("outcome") or None,
    )
    for item in items:
        _relativize_steps(item)

    return web.json_response(
        {
            "messages": items,
            "chain": _pipeline_chain(),
            "chains": _branch_chains(),
            "branches": _branch_names(),
            "summary": flow_summary(cfg.CONFIG_DB, has_content_only=not include_empty),
            "limit": limit,
        }
    )


@handle_errors("flow detail")
async def flow_detail_handler(request: web.Request) -> web.Response:
    """One message: route with reasons, raw envelope and the file it produced."""
    message_id = int(request.match_info["id"])
    item = get_flow_item(cfg.CONFIG_DB, message_id)
    if item is None:
        return web.json_response({"success": False, "error": "Meddelande hittades inte"}, status=404)

    output = None
    for step in reversed(item["steps"]):
        output = _read_output_preview(step.get("output_file"))
        if output:
            break
    _relativize_steps(item)

    # Every run of every attempt with its raw events, for the Händelser tab.
    runs = get_runs_for_message(cfg.CONFIG_DB, message_id)
    for run in runs:
        run["events"] = get_events_for_run(cfg.CONFIG_DB, run["id"])

    return web.json_response(
        {"message": item, "chain": _pipeline_chain(), "chains": _branch_chains(), "output": output, "runs": runs}
    )
