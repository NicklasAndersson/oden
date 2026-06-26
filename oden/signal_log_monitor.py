"""Monitor signal-cli log output for known receive failures."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from oden.signal_manager import get_effective_signal_cli_log_file

logger = logging.getLogger(__name__)


@dataclass
class _MonitorState:
    offset: int = 0
    log_path: Path | None = None


_state = _MonitorState()
_status: dict[str, object] = {
    "enabled": False,
    "available": False,
    "severity": "info",
    "message": "signal-cli loggning är avstängd.",
    "issue_detected": False,
    "issue_code": None,
    "last_scan_utc": None,
    "log_file": None,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_signal_log_status() -> dict[str, object]:
    """Return a shallow copy of latest monitor status."""
    return dict(_status)


def _set_status(**kwargs: object) -> None:
    _status.update(kwargs)
    _status["last_scan_utc"] = _utc_now()


def _find_issue(text: str) -> tuple[str, str] | None:
    lowered = text.lower()

    if "getserverguid" in lowered and "nullpointerexception" in lowered:
        return (
            "get_server_guid_npe",
            "signal-cli visar getServerGuid/NullPointerException i loggen (känd receive-störning).",
        )
    if "nosessionexception" in lowered:
        return ("no_session_exception", "signal-cli visar NoSessionException i loggen.")
    if "nullpointerexception" in lowered:
        return ("null_pointer_exception", "signal-cli visar NullPointerException i loggen.")

    return None


def scan_signal_cli_log_once() -> None:
    """Scan new log data and update monitor state."""
    log_file = get_effective_signal_cli_log_file()

    if not log_file:
        _state.offset = 0
        _state.log_path = None
        _set_status(
            enabled=False,
            available=False,
            severity="info",
            message="signal-cli loggning är avstängd. Övervakning körs inte.",
            issue_detected=False,
            issue_code=None,
            log_file=None,
        )
        return

    log_path = log_file.expanduser()
    _set_status(enabled=True, log_file=str(log_path))

    if not log_path.exists():
        _state.offset = 0
        _state.log_path = log_path
        _set_status(
            available=False,
            severity="info",
            message="signal-cli loggfil hittades inte ännu.",
            issue_detected=False,
            issue_code=None,
        )
        return

    if _state.log_path != log_path:
        _state.offset = 0
        _state.log_path = log_path

    try:
        file_size = log_path.stat().st_size
        if file_size < _state.offset:
            _state.offset = 0

        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(_state.offset)
            chunk = f.read()
            _state.offset = f.tell()
    except OSError as e:
        _set_status(
            available=False,
            severity="info",
            message=f"Kunde inte läsa signal-cli loggfil: {e}",
            issue_detected=False,
            issue_code=None,
        )
        return

    issue = _find_issue(chunk)
    if issue:
        issue_code, message = issue
        _set_status(
            available=True,
            severity="warning",
            message=message,
            issue_detected=True,
            issue_code=issue_code,
        )
        return

    _set_status(
        available=True,
        severity="info",
        message="signal-cli logg övervakas. Inga kända felmönster hittades.",
        issue_detected=False,
        issue_code=None,
    )


async def monitor_signal_cli_log(stop_event: asyncio.Event, interval_seconds: int = 30) -> None:
    """Periodically scan the configured signal-cli log file.

    The monitor is intentionally informational when log output is disabled.
    """
    while not stop_event.is_set():
        scan_signal_cli_log_once()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break
