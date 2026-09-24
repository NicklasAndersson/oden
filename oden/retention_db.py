"""Retention for Oden's DB-first message tables (raw_messages + pipeline runs/events).

Two limits, both set in the web GUI (Avancerat → Lagring):

* ``raw_message_retention_days`` — rows older than this are deleted.
* ``raw_message_max_mb`` — when the stored raw envelopes exceed this, the
  oldest messages are deleted until they fit (0 = no size limit). TAK
  messages with attachments carry them inline as base64, so size matters.

``run_retention_loop`` runs the cleanup once at startup and then every hour,
independent of Signal — TAK-only installations are cleaned too. Only the
database is pruned; notes already written to the vault are never touched.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RETENTION_INTERVAL_SECONDS = 3600
# VACUUM rewrites the whole file, so only when enough space is actually free.
_VACUUM_MIN_FREE_BYTES = 8 * 1024 * 1024
_VACUUM_MIN_FREE_RATIO = 0.25

# Result of the latest cleanup, for the GUI.
last_cleanup: dict[str, Any] | None = None


def _cutoff_utc(retention_days: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _delete_messages(cursor: sqlite3.Cursor, where: str, params: tuple) -> tuple[int, int, int]:
    """Delete raw_messages matching ``where`` with their runs and events. Returns (messages, runs, events)."""
    cursor.execute(
        f"""
        DELETE FROM pipeline_events
        WHERE run_id IN (
            SELECT id FROM pipeline_runs WHERE message_id IN (SELECT id FROM raw_messages WHERE {where})
        )
        """,
        params,
    )
    events = cursor.rowcount
    cursor.execute(
        f"DELETE FROM pipeline_runs WHERE message_id IN (SELECT id FROM raw_messages WHERE {where})",
        params,
    )
    runs = cursor.rowcount
    cursor.execute(f"DELETE FROM raw_messages WHERE {where}", params)
    return cursor.rowcount, runs, events


def _size_cutoff_id(cursor: sqlite3.Cursor, max_bytes: int) -> int | None:
    """Highest message id to delete so the rest fits in ``max_bytes``, or None if it already fits."""
    total = cursor.execute("SELECT COALESCE(SUM(LENGTH(CAST(envelope_raw AS BLOB))), 0) FROM raw_messages").fetchone()[
        0
    ]
    if total <= max_bytes:
        return None
    excess = total - max_bytes
    freed = 0
    for message_id, size in cursor.execute(
        "SELECT id, LENGTH(CAST(envelope_raw AS BLOB)) FROM raw_messages ORDER BY id ASC"
    ):
        freed += size or 0
        if freed >= excess:
            return message_id
    return None


def cleanup_old_data(db_path: Path, retention_days: int, max_mb: int = 0) -> dict[str, int]:
    """Delete old rows (by age, then by size) from raw_messages and the pipeline tables.

    Returns a summary with deleted row counts.
    """
    summary = {
        "retention_days": retention_days,
        "max_mb": max_mb,
        "deleted_raw_messages": 0,
        "deleted_pipeline_runs": 0,
        "deleted_pipeline_events": 0,
        "deleted_for_size": 0,
    }
    if retention_days < 1:
        return summary

    cutoff = _cutoff_utc(retention_days)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN")

        # Events age out on their own too (a kept message can have old reprocess events).
        cursor.execute("DELETE FROM pipeline_events WHERE occurred_at < ?", (cutoff,))
        summary["deleted_pipeline_events"] += cursor.rowcount

        messages, runs, events = _delete_messages(cursor, "created_at < ?", (cutoff,))
        summary["deleted_raw_messages"] += messages
        summary["deleted_pipeline_runs"] += runs
        summary["deleted_pipeline_events"] += events

        if max_mb and max_mb > 0:
            last_id = _size_cutoff_id(cursor, max_mb * 1024 * 1024)
            if last_id is not None:
                messages, runs, events = _delete_messages(cursor, "id <= ?", (last_id,))
                summary["deleted_raw_messages"] += messages
                summary["deleted_pipeline_runs"] += runs
                summary["deleted_pipeline_events"] += events
                summary["deleted_for_size"] = messages

        conn.commit()
        return summary
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def vacuum_if_worthwhile(db_path: Path) -> bool:
    """Give freed pages back to the filesystem when a real share of the file is free."""
    conn = sqlite3.connect(db_path)
    try:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        free = conn.execute("PRAGMA freelist_count").fetchone()[0]
        if free * page_size < _VACUUM_MIN_FREE_BYTES or free < pages * _VACUUM_MIN_FREE_RATIO:
            return False
        conn.execute("VACUUM")
        return True
    finally:
        conn.close()


def storage_stats(db_path: Path) -> dict[str, Any]:
    """What the message tables hold right now, for the GUI."""
    conn = sqlite3.connect(db_path)
    try:
        messages, raw_bytes, oldest, newest = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(envelope_raw AS BLOB))), 0), MIN(created_at), MAX(created_at) FROM raw_messages"
        ).fetchone()
        tak = conn.execute("SELECT COUNT(*) FROM raw_messages WHERE source_number LIKE 'tak:%'").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0]
    finally:
        conn.close()
    return {
        "messages": messages,
        "tak_messages": tak,
        "raw_bytes": raw_bytes,
        "pipeline_runs": runs,
        "pipeline_events": events,
        "oldest": oldest,
        "newest": newest,
        "db_file_bytes": db_path.stat().st_size if db_path.exists() else 0,
    }


def run_cleanup_now() -> dict[str, Any]:
    """One cleanup with the current settings; logs and records the result."""
    global last_cleanup
    from oden import config as cfg

    if not cfg.CONFIG_DB.exists():  # never create a database just to clean it
        return {"skipped": True}
    summary = cleanup_old_data(
        cfg.CONFIG_DB,
        int(cfg.RAW_MESSAGE_RETENTION_DAYS or 30),
        int(getattr(cfg, "RAW_MESSAGE_MAX_MB", 0) or 0),
    )
    deleted = summary["deleted_raw_messages"] + summary["deleted_pipeline_runs"] + summary["deleted_pipeline_events"]
    summary["vacuumed"] = vacuum_if_worthwhile(cfg.CONFIG_DB) if deleted else False
    summary["at"] = datetime.now(timezone.utc).isoformat()
    if deleted:
        logger.info(
            "Rensning: %d meddelanden (%d för storleksgränsen), %d körningar, %d händelser borttagna "
            "(%d dagar, max %s MB)%s",
            summary["deleted_raw_messages"],
            summary["deleted_for_size"],
            summary["deleted_pipeline_runs"],
            summary["deleted_pipeline_events"],
            summary["retention_days"],
            summary["max_mb"] or "∞",
            ", databasfilen komprimerad" if summary["vacuumed"] else "",
        )
    last_cleanup = summary
    return summary


async def run_retention_loop(stop: asyncio.Event, interval: float = RETENTION_INTERVAL_SECONDS) -> None:
    """Clean up at startup and then every ``interval`` seconds until ``stop`` is set.

    Runs in a worker thread so a large delete or VACUUM never blocks the web GUI.
    """
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_cleanup_now)
        except Exception as exc:
            logger.warning("Rensning av meddelandedatabasen misslyckades: %r", exc)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
