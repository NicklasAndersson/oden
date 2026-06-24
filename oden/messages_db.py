"""
Raw message storage for Oden 3.0 DB-first pipeline.

Each incoming Signal envelope is stored verbatim before any processing.
Status lifecycle: received → queued → processing → processed | failed | ignored
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


# Valid message statuses
STATUS_RECEIVED = "received"
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_PROCESSED = "processed"
STATUS_FAILED = "failed"
STATUS_IGNORED = "ignored"


def create_raw_message(
    db_path: Path,
    account: str,
    raw_message: dict[str, Any],
) -> int:
    """
    Persist a raw Signal message before any pipeline processing.

    Returns the new row id (message_id).
    """
    # Incoming payload can be either:
    # - envelope dict (sourceNumber, dataMessage, ...)
    # - wrapper dict with {"envelope": {...}, ...}
    envelope = raw_message.get("envelope") if isinstance(raw_message, dict) else None
    if not isinstance(envelope, dict):
        envelope = raw_message

    dm = envelope.get("dataMessage") or {}
    group_v2 = dm.get("groupV2") or {}

    ts_ms: int = envelope.get("timestamp", 0)
    if ts_ms:
        ts_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    else:
        ts_utc = _now()

    attachments = dm.get("attachments") or []

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO raw_messages
                (account, timestamp_utc, envelope_raw,
                 source_number, source_name, group_id, group_name,
                 message_body, has_attachments, status, status_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account,
                ts_utc,
                json.dumps(raw_message, ensure_ascii=False),
                envelope.get("sourceNumber"),
                envelope.get("sourceName"),
                group_v2.get("id"),
                group_v2.get("name"),
                dm.get("message"),
                1 if attachments else 0,
                STATUS_RECEIVED,
                _now(),
            ),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def update_message_status(
    db_path: Path,
    message_id: int,
    status: str,
    *,
    group_name: str | None = None,
) -> None:
    """Update the processing status of a stored message."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if group_name is not None:
            cursor.execute(
                "UPDATE raw_messages SET status = ?, status_timestamp = ?, group_name = ? WHERE id = ?",
                (status, _now(), group_name, message_id),
            )
        else:
            cursor.execute(
                "UPDATE raw_messages SET status = ?, status_timestamp = ? WHERE id = ?",
                (status, _now(), message_id),
            )
        conn.commit()
    finally:
        conn.close()


def list_messages(
    db_path: Path,
    *,
    account: str | None = None,
    status: str | None = None,
    group_id: str | None = None,
    has_content_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Return recent messages with optional filtering.

    Does NOT include the raw envelope_raw blob (use get_message_detail for that).
    """
    conditions: list[str] = []
    params: list[Any] = []

    if account:
        conditions.append("account = ?")
        params.append(account)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if group_id:
        conditions.append("group_id = ?")
        params.append(group_id)
    if has_content_only:
        conditions.append("COALESCE(TRIM(message_body), '') != ''")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT id, account, timestamp_utc, source_number, source_name,
                   group_id, group_name, message_body, has_attachments,
                   status, status_timestamp, created_at
            FROM raw_messages
            {where}
            ORDER BY timestamp_utc DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_message_detail(
    db_path: Path,
    message_id: int,
) -> dict[str, Any] | None:
    """Return full message record including raw envelope JSON."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM raw_messages WHERE id = ?",
            (message_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        # Parse envelope_raw back to dict for callers
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            result["envelope_raw"] = json.loads(result["envelope_raw"])
        return result
    finally:
        conn.close()


def get_message_stats(
    db_path: Path,
    *,
    account: str | None = None,
) -> dict[str, Any]:
    """Return aggregate counts by status."""
    conditions: list[str] = []
    params: list[Any] = []
    if account:
        conditions.append("account = ?")
        params.append(account)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT status, COUNT(*) FROM raw_messages {where} GROUP BY status",
            params,
        )
        counts: dict[str, int] = {row[0]: row[1] for row in cursor.fetchall()}
    finally:
        conn.close()

    total = sum(counts.values())
    return {
        "total": total,
        "received": counts.get(STATUS_RECEIVED, 0),
        "queued": counts.get(STATUS_QUEUED, 0),
        "processing": counts.get(STATUS_PROCESSING, 0),
        "processed": counts.get(STATUS_PROCESSED, 0),
        "failed": counts.get(STATUS_FAILED, 0),
        "ignored": counts.get(STATUS_IGNORED, 0),
    }
