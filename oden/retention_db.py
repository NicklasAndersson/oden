"""Retention cleanup for Oden DB-first message tables."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _cutoff_utc(retention_days: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def cleanup_old_data(db_path: Path, retention_days: int) -> dict[str, int]:
    """Delete old rows from raw_messages and pipeline event/run tables.

    Returns a summary with deleted row counts.
    """
    if retention_days < 1:
        return {
            "retention_days": retention_days,
            "deleted_raw_messages": 0,
            "deleted_pipeline_runs": 0,
            "deleted_pipeline_events": 0,
        }

    cutoff = _cutoff_utc(retention_days)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN")

        cursor.execute(
            """
            DELETE FROM pipeline_events
            WHERE run_id IN (
                SELECT id FROM pipeline_runs
                WHERE message_id IN (
                    SELECT id FROM raw_messages WHERE created_at < ?
                )
            )
            """,
            (cutoff,),
        )
        deleted_events = cursor.rowcount

        cursor.execute(
            "DELETE FROM pipeline_runs WHERE message_id IN (SELECT id FROM raw_messages WHERE created_at < ?)",
            (cutoff,),
        )
        deleted_runs = cursor.rowcount

        cursor.execute("DELETE FROM raw_messages WHERE created_at < ?", (cutoff,))
        deleted_messages = cursor.rowcount

        conn.commit()

        return {
            "retention_days": retention_days,
            "deleted_raw_messages": deleted_messages,
            "deleted_pipeline_runs": deleted_runs,
            "deleted_pipeline_events": deleted_events,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
