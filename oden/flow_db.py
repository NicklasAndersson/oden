"""Read model for the Flöde view: every stored message with the route it took.

Joins ``raw_messages`` with the latest attempt of its ``pipeline_runs`` and the
reason each pipeline gave (``pipeline_events.details.reason``), so the web GUI
can show where a message went and why in one request.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any

SOURCE_TAK = "tak"
_TAK_PREFIX = "tak:"

# A run whose pipeline handled the message ends the chain; the kind shown for it
# depends on the message status it produced.
OUTCOME_HANDLED = "handled"
OUTCOME_IGNORED = "ignored"
OUTCOME_SKIPPED = "skipped"
OUTCOME_FAILED = "failed"
OUTCOME_RUNNING = "running"
OUTCOME_ROUTE = "route"  # the vägval: which branch the message went to

ROUTER = "router"  # same as routing.ROUTER; not imported to keep flow_db free of config

_RUN_OUTCOME = {
    "done": OUTCOME_HANDLED,
    "skipped": OUTCOME_SKIPPED,
    "failed": OUTCOME_FAILED,
    "running": OUTCOME_RUNNING,
    "pending": OUTCOME_RUNNING,
}

_HAS_CONTENT = "(COALESCE(TRIM(message_body), '') != '' OR has_attachments = 1)"


def source_key(account: str | None, source_number: str | None) -> str:
    """``tak`` for messages from the TAK listener, else ``signal:<account>``."""
    if source_number and source_number.startswith(_TAK_PREFIX):
        return SOURCE_TAK
    return f"signal:{account or ''}"


def _source_condition(source: str | None) -> tuple[str | None, list[Any]]:
    if not source:
        return None, []
    if source == SOURCE_TAK:
        return "source_number LIKE 'tak:%'", []
    if source.startswith("signal:"):
        return "account = ? AND COALESCE(source_number, '') NOT LIKE 'tak:%'", [source.removeprefix("signal:")]
    return "0", []


def _latest_attempt(runs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Split runs (ordered by id) into attempts and return the last one.

    Within one attempt each pipeline runs at most once, so a repeated pipeline
    name marks the start of a reprocess.
    """
    attempts: list[list[dict[str, Any]]] = []
    seen: set[str] = set()
    for run in runs:
        if not attempts or run["pipeline_name"] in seen:
            attempts.append([])
            seen = set()
        attempts[-1].append(run)
        seen.add(run["pipeline_name"])
    return (attempts[-1] if attempts else []), len(attempts)


def _load_steps(conn: sqlite3.Connection, message_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not message_ids:
        return {}
    placeholders = ",".join("?" for _ in message_ids)
    rows = conn.execute(
        f"""
        SELECT r.id, r.message_id, r.pipeline_name, r.status, r.output_file, r.error_message,
               e.event_type, e.details
        FROM pipeline_runs r
        LEFT JOIN pipeline_events e
               ON e.run_id = r.id
              AND e.event_type IN ('pipeline_completed', 'pipeline_skipped', 'pipeline_side_effect', 'pipeline_warning')
        WHERE r.message_id IN ({placeholders})
        ORDER BY r.id ASC, e.id ASC
        """,
        message_ids,
    ).fetchall()

    runs_by_message: dict[int, list[dict[str, Any]]] = {}
    runs_by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        run = runs_by_id.get(row["id"])
        if run is None:
            run = {
                "run_id": row["id"],
                "pipeline_name": row["pipeline_name"],
                "status": row["status"],
                "output_file": row["output_file"],
                "error": row["error_message"],
                "reason": None,
                "side_effect": None,
                "warnings": [],
                "branch": None,
                "branch_name": None,
                "ignore": False,
            }
            runs_by_id[row["id"]] = run
            runs_by_message.setdefault(row["message_id"], []).append(run)
        if not row["event_type"]:
            continue
        details: Any = None
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            details = json.loads(row["details"]) if row["details"] else None
        if not isinstance(details, dict):
            continue
        if row["event_type"] == "pipeline_side_effect":
            run["side_effect"] = details.get("message")
        elif row["event_type"] == "pipeline_warning":
            if details.get("message"):
                run["warnings"].append(details["message"])
        else:
            if details.get("reason"):
                run["reason"] = details["reason"]
            if details.get("branch"):
                run["branch"] = details["branch"]
                run["branch_name"] = details.get("branch_name") or details["branch"]
                run["ignore"] = bool(details.get("ignore"))
    return runs_by_message


def _to_steps(runs: list[dict[str, Any]], message_status: str) -> list[dict[str, Any]]:
    steps = []
    for run in runs:
        outcome = _RUN_OUTCOME.get(run["status"], OUTCOME_SKIPPED)
        if run["pipeline_name"] == ROUTER:
            outcome = OUTCOME_IGNORED if run["ignore"] else OUTCOME_ROUTE
        elif outcome == OUTCOME_HANDLED and message_status == "ignored":
            outcome = OUTCOME_IGNORED
        steps.append(
            {
                "pipeline": run["pipeline_name"],
                "outcome": outcome,
                "reason": run["reason"],
                "side_effect": run["side_effect"],
                "output_file": run["output_file"],
                "error": run["error"],
                "warnings": run["warnings"],
            }
        )
    return steps


def _row_to_item(row: sqlite3.Row, runs: list[dict[str, Any]]) -> dict[str, Any]:
    item = dict(row)
    latest, attempts = _latest_attempt(runs)
    item["source"] = source_key(item["account"], item["source_number"])
    item["steps"] = _to_steps(latest, item["status"])
    item["attempts"] = attempts
    route = next((r for r in latest if r["pipeline_name"] == ROUTER), None)
    item["branch"] = route["branch"] if route else None
    item["branch_name"] = route["branch_name"] if route else None
    return item


def list_flow(
    db_path: Path,
    *,
    source: str | None = None,
    status: str | None = None,
    has_content_only: bool = True,
    limit: int = 100,
    before_id: int | None = None,
) -> list[dict[str, Any]]:
    """Newest-first messages with the steps of their latest pipeline attempt.

    ``status`` may name several statuses, comma-separated (``received,queued``).
    """
    conditions: list[str] = []
    params: list[Any] = []

    src_sql, src_params = _source_condition(source)
    if src_sql:
        conditions.append(src_sql)
        params.extend(src_params)
    statuses = [s.strip() for s in (status or "").split(",") if s.strip()]
    if statuses:
        conditions.append(f"status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)
    if has_content_only:
        conditions.append(_HAS_CONTENT)
    if before_id:
        conditions.append("id < ?")
        params.append(before_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT id, account, timestamp_utc, source_number, source_name,
                   group_id, group_name, message_body, has_attachments,
                   status, status_timestamp
            FROM raw_messages
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        runs = _load_steps(conn, [row["id"] for row in rows])
        return [_row_to_item(row, runs.get(row["id"], [])) for row in rows]
    finally:
        conn.close()


def get_flow_item(db_path: Path, message_id: int) -> dict[str, Any] | None:
    """One message with its latest-attempt steps and the raw envelope."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, account, timestamp_utc, source_number, source_name,
                   group_id, group_name, message_body, has_attachments,
                   status, status_timestamp, envelope_raw
            FROM raw_messages WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
        if row is None:
            return None
        runs = _load_steps(conn, [message_id])
        item = _row_to_item(row, runs.get(message_id, []))
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            item["envelope_raw"] = json.loads(item["envelope_raw"])
        return item
    finally:
        conn.close()


def flow_summary(db_path: Path, *, has_content_only: bool = True) -> dict[str, Any]:
    """Counts per source and per status, plus how many content-less rows there are.

    With ``has_content_only`` (the Flöde default) the counts cover what the list
    shows; ``hidden_without_content`` is always the number of content-less rows.
    """
    shown = _HAS_CONTENT if has_content_only else "1"
    conn = sqlite3.connect(db_path)
    try:
        by_source: dict[str, int] = {}
        for account, is_tak, count in conn.execute(
            f"""
            SELECT account, COALESCE(source_number, '') LIKE 'tak:%' AS is_tak, COUNT(*)
            FROM raw_messages WHERE {shown}
            GROUP BY account, is_tak
            """
        ):
            key = SOURCE_TAK if is_tak else f"signal:{account or ''}"
            by_source[key] = by_source.get(key, 0) + count

        by_status = dict(
            conn.execute(f"SELECT status, COUNT(*) FROM raw_messages WHERE {shown} GROUP BY status").fetchall()
        )
        hidden = conn.execute(f"SELECT COUNT(*) FROM raw_messages WHERE NOT {_HAS_CONTENT}").fetchone()[0]
        return {
            "sources": by_source,
            "statuses": by_status,
            "total": sum(by_status.values()),
            "hidden_without_content": hidden,
        }
    finally:
        conn.close()
