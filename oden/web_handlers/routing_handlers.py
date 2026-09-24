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
    return web.json_response(
        {
            "routing": routing,
            "sources": _sources(routing, by_source),
            "branch_counts_24h": by_branch,
            "pipelines": _pipeline_meta(),
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
