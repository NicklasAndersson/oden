"""
Pipeline run storage for Oden 3.0 DB-first pipeline.

Tracks every pipeline execution per message with status and structured events.
Status lifecycle: pending → running → done | failed | skipped
"""

import contextlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

# Valid pipeline run statuses
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


def start_pipeline_run(
    db_path: Path,
    message_id: int,
    pipeline_name: str,
) -> int:
    """
    Create a pipeline_runs row in 'running' state.

    Returns the new run_id.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO pipeline_runs
                (message_id, pipeline_name, status, started_at)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, pipeline_name, STATUS_RUNNING, _now()),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def _finish_run(
    db_path: Path,
    run_id: int,
    status: str,
    *,
    output_file: str | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE pipeline_runs SET status = ?, completed_at = ?, output_file = ? WHERE id = ?",
            (status, _now(), output_file, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def complete_pipeline_run(
    db_path: Path,
    run_id: int,
    *,
    output_file: str | None = None,
) -> None:
    """Mark a pipeline run as successfully done."""
    _finish_run(db_path, run_id, STATUS_DONE, output_file=output_file)


def skip_pipeline_run(
    db_path: Path,
    run_id: int,
) -> None:
    """Mark a pipeline run as skipped (message did not match this pipeline)."""
    _finish_run(db_path, run_id, STATUS_SKIPPED)


def fail_pipeline_run(
    db_path: Path,
    run_id: int,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Mark a pipeline run as failed with optional error details."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE pipeline_runs SET status = ?, completed_at = ?, error_code = ?, error_message = ? WHERE id = ?",
            (STATUS_FAILED, _now(), error_code, error_message, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def append_pipeline_event(
    db_path: Path,
    run_id: int,
    event_type: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Append a structured event to a pipeline run's event log."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO pipeline_events (run_id, event_type, occurred_at, details)
            VALUES (?, ?, ?, ?)
            """,
            (
                run_id,
                event_type,
                _now(),
                json.dumps(details, ensure_ascii=False) if details else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_runs_for_message(
    db_path: Path,
    message_id: int,
) -> list[dict[str, Any]]:
    """Return all pipeline runs for a given message, ordered by started_at."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, pipeline_name, status, started_at, completed_at,
                   output_file, error_code, error_message
            FROM pipeline_runs
            WHERE message_id = ?
            ORDER BY started_at ASC
            """,
            (message_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_events_for_run(
    db_path: Path,
    run_id: int,
) -> list[dict[str, Any]]:
    """Return all events for a pipeline run, ordered by occurred_at."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, event_type, occurred_at, details
            FROM pipeline_events
            WHERE run_id = ?
            ORDER BY occurred_at ASC
            """,
            (run_id,),
        )
        rows = []
        for row in cursor.fetchall():
            r = dict(row)
            if r["details"]:
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    r["details"] = json.loads(r["details"])
            rows.append(r)
        return rows
    finally:
        conn.close()
