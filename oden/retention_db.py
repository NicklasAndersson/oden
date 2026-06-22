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

        # First remove pipeline events that are old on their own.
        cursor.execute("DELETE FROM pipeline_events WHERE occurred_at < ?", (cutoff,))
        deleted_events_by_age = cursor.rowcount

        # Then remove runs/messages by raw message age to avoid orphaned rows.
        cursor.execute("SELECT id FROM raw_messages WHERE created_at < ?", (cutoff,))
        old_message_ids = [row[0] for row in cursor.fetchall()]

        deleted_runs = 0
        deleted_events_for_runs = 0
        deleted_messages = 0

        if old_message_ids:
            placeholders = ",".join("?" for _ in old_message_ids)

            cursor.execute(
                f"SELECT id FROM pipeline_runs WHERE message_id IN ({placeholders})",
                old_message_ids,
            )
            run_ids = [row[0] for row in cursor.fetchall()]

            if run_ids:
                run_placeholders = ",".join("?" for _ in run_ids)
                cursor.execute(
                    f"DELETE FROM pipeline_events WHERE run_id IN ({run_placeholders})",
                    run_ids,
                )
                deleted_events_for_runs = cursor.rowcount

            cursor.execute(
                f"DELETE FROM pipeline_runs WHERE message_id IN ({placeholders})",
                old_message_ids,
            )
            deleted_runs = cursor.rowcount

            cursor.execute(
                f"DELETE FROM raw_messages WHERE id IN ({placeholders})",
                old_message_ids,
            )
            deleted_messages = cursor.rowcount

        conn.commit()

        return {
            "retention_days": retention_days,
            "deleted_raw_messages": deleted_messages,
            "deleted_pipeline_runs": deleted_runs,
            "deleted_pipeline_events": deleted_events_by_age + deleted_events_for_runs,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
