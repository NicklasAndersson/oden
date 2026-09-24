"""Vägval and branches (grenar) for the Pipelines tab.

GET returns the routing in effect plus everything the tab needs to show it:
the known sources (Signal groups, direct messages, TAK) with the branch each
goes to, how many messages each source and branch saw in the last 24 hours,
and the pipelines a branch can contain. PUT validates and stores a new routing;
the orchestrator reads it for the next message.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from oden import config as cfg
from oden.config_db import set_config_value
from oden.dry_run import build_test_message, dry_run, publish_to_tak
from oden.groups_db import get_all_groups
from oden.routing import (
    ROUTER,
    STEP_PIPELINES,
    load_routing,
    normalize_routing,
)
from oden.web_handlers._helpers import handle_errors, parse_json_body

logger = logging.getLogger(__name__)


def _since_24h() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _counts(db_path: Path) -> tuple[dict[str, int], dict[str, int]]:
    """``(per source key, per branch id)`` message counts for the last 24 hours."""
    if not db_path.exists():
        return {}, {}
    since = _since_24h()
    by_source: dict[str, int] = {}
    by_branch: dict[str, int] = {}
    conn = sqlite3.connect(db_path)
    try:
        for is_tak, group_id, group_name, count in conn.execute(
            """
            SELECT COALESCE(source_number, '') LIKE 'tak:%', group_id, group_name, COUNT(*)
            FROM raw_messages
            WHERE created_at >= ? AND (COALESCE(TRIM(message_body), '') != '' OR has_attachments = 1)
            GROUP BY 1, 2, 3
            """,
            (since,),
        ):
            if is_tak:
                key = "source:tak"
            elif group_name or group_id:
                key = f"group:{group_name}" if group_name else f"group_id:{group_id}"
            else:
                key = "source:direct"
            by_source[key] = by_source.get(key, 0) + count
        try:
            rows = conn.execute(
                """
                SELECT json_extract(e.details, '$.branch'), COUNT(*)
                FROM pipeline_events e JOIN pipeline_runs r ON r.id = e.run_id
                WHERE r.pipeline_name = ? AND e.event_type = 'pipeline_completed' AND e.occurred_at >= ?
                GROUP BY 1
                """,
                (ROUTER, since),
            ).fetchall()
        except sqlite3.OperationalError:  # SQLite without JSON1
            rows = []
        by_branch = {branch: count for branch, count in rows if branch}
    finally:
        conn.close()
    return by_source, by_branch


def _step_stats(db_path: Path) -> dict[str, dict[str, dict[str, int]]]:
    """Branch id → pipeline → {handled, skipped, failed, side} over the last 24 hours.

    A run belongs to the branch of the latest vägval (router run) before it for
    the same message — reprocessing may have routed an old message differently.
    """
    stats: dict[str, dict[str, dict[str, int]]] = {}
    if not db_path.exists():
        return stats
    since = _since_24h()
    conn = sqlite3.connect(db_path)
    try:
        try:
            routes = conn.execute(
                """
                SELECT r.message_id, r.id, json_extract(e.details, '$.branch')
                FROM pipeline_runs r JOIN pipeline_events e ON e.run_id = r.id
                WHERE r.pipeline_name = ? AND e.event_type = 'pipeline_completed' AND r.started_at >= ?
                ORDER BY r.id
                """,
                (ROUTER, since),
            ).fetchall()
        except sqlite3.OperationalError:
            return stats
        runs = conn.execute(
            """
            SELECT r.message_id, r.id, r.pipeline_name, r.status,
                   EXISTS(SELECT 1 FROM pipeline_events e WHERE e.run_id = r.id AND e.event_type = 'pipeline_side_effect')
            FROM pipeline_runs r
            WHERE r.pipeline_name != ? AND r.started_at >= ?
            ORDER BY r.id
            """,
            (ROUTER, since),
        ).fetchall()
    finally:
        conn.close()

    routes_by_message: dict[int, list[tuple[int, str]]] = {}
    for message_id, run_id, branch in routes:
        routes_by_message.setdefault(message_id, []).append((run_id, branch))
    for message_id, run_id, pipeline, status, side in runs:
        branch = None
        for route_id, route_branch in routes_by_message.get(message_id, []):
            if route_id < run_id:
                branch = route_branch
        if not branch:
            continue
        counts = stats.setdefault(branch, {}).setdefault(pipeline, {"handled": 0, "skipped": 0, "failed": 0, "side": 0})
        if side:
            counts["side"] += 1
        elif status == "done":
            counts["handled"] += 1
        elif status == "failed":
            counts["failed"] += 1
        else:
            counts["skipped"] += 1
    return stats


def _sources(routing: dict[str, Any], by_source: dict[str, int]) -> list[dict[str, Any]]:
    """Every source the operator may want to route: TAK, direct messages, known and seen groups."""
    names: set[str] = set()
    for group in get_all_groups(cfg.CONFIG_DB, account=cfg.SIGNAL_NUMBER):
        if group.get("name"):
            names.add(group["name"])
    for key in list(routing["assign"]) + list(by_source):
        if key.startswith("group:"):
            names.add(key.removeprefix("group:"))

    entries = [
        ("source:tak", "TAK", "tak"),
        ("source:direct", "Direktmeddelanden", "direct"),
        *((f"group:{name}", name, "group") for name in sorted(names, key=str.casefold)),
    ]
    # group_id keys only exist if someone assigned by id; show them too.
    entries += [(k, k.removeprefix("group_id:"), "group") for k in routing["assign"] if k.startswith("group_id:")]

    result = []
    for key, label, kind in entries:
        assigned = key in routing["assign"]
        result.append(
            {
                "key": key,
                "label": label,
                "kind": kind,
                "branch": routing["assign"].get(key, routing["default"]),
                "assigned": assigned,
                "count_24h": by_source.get(key, 0),
            }
        )
    return result


def _pipeline_meta() -> list[dict[str, Any]]:
    from oden.web_handlers.pipeline_handlers import _get_available_pipelines

    available = _get_available_pipelines()
    return [available[name] for name in STEP_PIPELINES if name in available]


@handle_errors("routing")
async def routing_handler(request: web.Request) -> web.Response:
    routing = load_routing(cfg)
    by_source, by_branch = await asyncio.to_thread(_counts, cfg.CONFIG_DB)
    step_stats = await asyncio.to_thread(_step_stats, cfg.CONFIG_DB)
    return web.json_response(
        {
            "routing": routing,
            "sources": _sources(routing, by_source),
            "branch_counts_24h": by_branch,
            "step_stats_24h": step_stats,
            "pipelines": _pipeline_meta(),
            "publish_to_tak": publish_to_tak(),
        }
    )


@handle_errors("save routing")
@parse_json_body
async def routing_save_handler(request: web.Request) -> web.Response:
    try:
        routing = normalize_routing(request["json_body"].get("routing"))
    except ValueError as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=400)

    set_config_value(cfg.CONFIG_DB, "routing", routing)
    cfg.ROUTING = routing
    logger.info(
        "Vägval sparat: %d grenar, %d tilldelade källor, standard %s",
        len(routing["branches"]),
        len(routing["assign"]),
        routing["default"],
    )
    return web.json_response({"success": True, "routing": routing})


@handle_errors("test message")
@parse_json_body
async def routing_test_handler(request: web.Request) -> web.Response:
    """Testruta: the route a pasted message would take now. Writes and sends nothing."""
    body = request["json_body"]
    text = str(body.get("text") or "")
    source = str(body.get("source") or "source:direct")
    if not text.strip():
        return web.json_response({"success": False, "error": "Skriv eller klistra in ett meddelande"}, status=400)
    if len(text) > 20000:
        return web.json_response({"success": False, "error": "Meddelandet är för långt för Testrutan"}, status=400)
    if source not in ("source:tak", "source:direct") and not (source.startswith("group:") and len(source) > 6):
        return web.json_response({"success": False, "error": f"Okänd källa: {source!r}"}, status=400)

    group_id = None
    if source.startswith("group:"):
        name = source.removeprefix("group:")
        known = get_all_groups(cfg.CONFIG_DB, account=cfg.SIGNAL_NUMBER)
        group_id = next((g.get("id") for g in known if g.get("name") == name), None)

    result = await dry_run(build_test_message(text, source, group_id=group_id))
    return web.json_response({"success": True, **result})
