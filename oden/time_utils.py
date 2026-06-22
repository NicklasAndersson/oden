"""Shared time helpers for database timestamps."""

from __future__ import annotations

from datetime import datetime, timezone


def now_utc_iso_millis() -> str:
    """Return current UTC timestamp as ISO-8601 with milliseconds and Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
