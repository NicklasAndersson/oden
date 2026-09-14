"""Inbound CoT: TAK Server -> Oden.

A TAK Server pushes the *whole* common operational picture to every connected
client (position reports every ~30 s per user, tracks, chat). Landing all of
that in ``raw_messages`` would bury the vault, so everything here is about
throwing traffic away cheaply:

1. type / callsign filters (default: no friendly PLI)
2. own-echo guard (uids we published)
3. per-uid dedup — same place, same text, no new note
4. a hard per-minute ceiling

What survives is wrapped in a Signal-shaped envelope and pushed through the
normal pipeline chain, so it shows up in the message view, the vault, retention
and the group filter like anything else.

See docs/PLAN_TAK.md phase 3.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from oden import config as cfg
from oden.tak.cot import (
    UID_PREFIX,
    CotTypeMatcher,
    InboundCot,
    cot_to_inbound,
    distance_m,
    latlon_to_mgrs,
    raw_event_type,
)
from oden.tak.eight_s import is_8s_report, to_7s_message

logger = logging.getLogger(__name__)

INBOUND_GROUP_ID = "oden-tak-inbound"
OBSERVATION_HEADER = "TAK-OBSERVATION"  # deliberately not "... RAPPORT": must not re-parse as 7S

_INBOUND_DEFAULTS: dict[str, Any] = {
    "inbound_enabled": False,
    # Manually placed markers/points (a-{f,h,u,n}-G, b-m-p-*) and alerts (b-a-*).
    # Deliberately NOT bare a-f-* — that catches the flood of friendly PLI/tracks.
    "inbound_types": ["a-f-G", "a-h-*", "a-n-G", "a-u-*", "b-m-p-*", "b-a-*"],
    "inbound_callsign_allow": [],
    "inbound_callsign_deny": [],
    "inbound_min_move_m": 100.0,
    "inbound_max_per_minute": 60,
    "inbound_group_name": "TAK Inkommande",
}

# ponytail: crude cap so the dedup cache can't grow without bound on a busy
# server. On overflow we forget everything and re-learn — a handful of static
# markers get re-imported once, no worse.
_SEEN_CAP = 5000
# Distinct discarded CoT types the tally keeps. A server sends a handful; the cap
# is only so a broken or hostile peer cannot grow it without bound.
_TALLY_CAP = 32


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _count(tally: dict[str, int], key: str) -> None:
    """Increment, but never let an unknown peer grow the tally without bound."""
    if key in tally or len(tally) < _TALLY_CAP:
        tally[key] = tally.get(key, 0) + 1


def _content_signature(cot: InboundCot) -> str:
    """Text used to detect an unchanged repeat — remarks plus any custom_report fields."""
    return cot.remarks + "|" + str(sorted(cot.custom_report.items()))


@dataclass
class _Seen:
    lat: float
    lon: float
    signature: str  # remarks + custom_report fields, used to detect an unchanged repeat
    cot_type: str
    seen_at: float = 0.0  # unix time, only used to age the cache that survives a restart


# A marker deleted from the server long ago must not block a legitimate re-import
# forever, so the persisted cache forgets what it has not seen for this long.
_SEEN_MAX_AGE_S = 30 * 24 * 3600
# An unchanged repeat refreshes seen_at at most this often. Refreshing on every repeat
# would dirty the cache on each save for a server that republishes every ten seconds.
_SEEN_REFRESH_S = 24 * 3600


def load_seen(db_path: Path, *, now: float | None = None) -> dict[str, _Seen]:
    """The dedup cache from the previous run, most recently seen first.

    Without this a restart re-imports the server's whole live picture: a TAK
    Server republishes every active marker, and an empty cache reads each one as
    new. One restart is one duplicate note per live marker.

    Never raises. A database error means an empty cache and a re-import, which is
    the old behaviour — not a listener that refuses to run.
    """
    cutoff = (time.time() if now is None else now) - _SEEN_MAX_AGE_S
    try:
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            rows = conn.execute(
                "SELECT uid, lat, lon, signature, cot_type, seen_at FROM tak_inbound_seen"
                " WHERE seen_at >= ? ORDER BY seen_at DESC LIMIT ?",
                (cutoff, _SEEN_CAP),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("TAK: kunde inte läsa dedup-cachen (%s) — börjar om med tom cache", exc)
        return {}
    return {uid: _Seen(lat, lon, signature, cot_type, seen_at) for uid, lat, lon, signature, cot_type, seen_at in rows}


def save_seen(seen: dict[str, _Seen], db_path: Path) -> None:
    """Replace the stored dedup cache. Never raises — a failed write costs a re-import, nothing more."""
    try:
        # The second `conn` is the transaction: a crash mid-write leaves the previous cache.
        with contextlib.closing(sqlite3.connect(db_path)) as conn, conn:
            conn.execute("DELETE FROM tak_inbound_seen")
            conn.executemany(
                "INSERT INTO tak_inbound_seen (uid, lat, lon, signature, cot_type, seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                [(uid, s.lat, s.lon, s.signature, s.cot_type, s.seen_at) for uid, s in seen.items()],
            )
    except sqlite3.Error as exc:
        logger.warning("TAK: kunde inte spara dedup-cachen (%s)", exc)


class InboundFilter:
    """Decides whether one inbound CoT is worth a note. Pure, so it is testable."""

    def __init__(self, settings: dict[str, Any], *, seen: dict[str, _Seen] | None = None) -> None:
        merged = {**_INBOUND_DEFAULTS, **settings}
        self.types = _as_list(merged["inbound_types"])
        # Same patterns, compiled: this matcher runs on the raw pre-screen path
        # for every inbound event. cot_type_matches stays the reference version.
        self._type_matcher = CotTypeMatcher.from_patterns(self.types)
        self.allow = [c.lower() for c in _as_list(merged["inbound_callsign_allow"])]
        self.deny = [c.lower() for c in _as_list(merged["inbound_callsign_deny"])]
        self.min_move_m = _num(merged["inbound_min_move_m"], 100.0)
        self.max_per_minute = int(_num(merged["inbound_max_per_minute"], 60.0))
        self._seen: dict[str, _Seen] = dict(seen or {})
        # True when _seen changed since the last save, so a quiet server costs no writes.
        self.seen_dirty = False
        self._window_start = 0.0
        self._window_count = 0
        self.last_reject: str = ""  # why the most recent accept() returned False

    def _rate_limited(self, now: float) -> bool:
        if self.max_per_minute <= 0:
            return False
        if now - self._window_start >= 60.0:
            self._window_start = now
            self._window_count = 0
        self._window_count += 1
        return self._window_count > self.max_per_minute

    def seen_snapshot(self) -> dict[str, _Seen]:
        """A copy of the dedup state, for persisting it. The filter itself does no I/O."""
        return dict(self._seen)

    def prescreen_rejects(self, data: object) -> bool:
        """True only when the type whitelist *certainly* rejects this raw payload.

        Conservative by construction: anything the cheap read cannot decide
        returns False and goes on to the full parse and ``accept`` as before.
        ``accept`` remains the authoritative filter — this only lets the
        listener skip an XML parse that was doomed anyway, which is the
        difference between 14 us and 1 us for the position-report flood.

        Type only. The own-echo guard is deliberately not pre-screened: accept()
        tests the *sanitized* uid, so a raw-bytes comparison would not agree.
        """
        if not self.types:
            return False
        raw_type = raw_event_type(data)
        return raw_type is not None and not self._type_matcher.matches(raw_type)

    def accept(self, cot: InboundCot, *, now: float | None = None) -> bool:
        if cot.uid.startswith(UID_PREFIX):
            self.last_reject = "egen markör (eko)"
            return False
        if self.types and not self._type_matcher.matches(cot.cot_type):
            self.last_reject = f"typ {cot.cot_type} matchar inte inbound_types"
            return False

        callsign = cot.callsign.lower()
        if self.deny and any(d in callsign for d in self.deny):
            self.last_reject = f"callsign {cot.callsign} på deny-listan"
            return False
        if self.allow and not any(a in callsign for a in self.allow):
            self.last_reject = f"callsign {cot.callsign} inte på allow-listan"
            return False

        previous = self._seen.get(cot.uid)
        now_s = time.time() if now is None else now
        current = _Seen(cot.lat, cot.lon, _content_signature(cot), cot.cot_type, seen_at=now_s)
        if previous is not None:
            unchanged = (
                previous.cot_type == current.cot_type
                and previous.signature == current.signature
                and distance_m(previous.lat, previous.lon, current.lat, current.lon) < self.min_move_m
            )
            if unchanged:
                # Still live, so still seen: without this a marker that sits unchanged on the
                # server for _SEEN_MAX_AGE_S is forgotten and re-imported on the next restart.
                if now_s - previous.seen_at >= _SEEN_REFRESH_S:
                    self._seen[cot.uid] = replace(previous, seen_at=now_s)
                    self.seen_dirty = True
                self.last_reject = "oförändrad sedan tidigare (dedup)"
                return False

        if len(self._seen) >= _SEEN_CAP:
            self._seen.clear()
        self._seen[cot.uid] = current  # record content even if rate-limiting drops this instance
        self.seen_dirty = True

        if self._rate_limited(time.monotonic() if now is None else now):
            self.last_reject = f"över {self.max_per_minute} CoT/minut"
            logger.warning("TAK: fler än %s inkommande CoT/minut — släpper resten", self.max_per_minute)
            return False

        self.last_reject = ""
        return True


def render_observation(cot: InboundCot) -> str:
    """Human-readable note body. Must not look like a structured report header."""
    mgrs = latlon_to_mgrs(cot.lat, cot.lon)
    position = f"{mgrs} ({cot.lat:.5f}, {cot.lon:.5f})" if mgrs else f"{cot.lat:.5f}, {cot.lon:.5f}"
    local_time = cot.event_time.astimezone(cfg.TIMEZONE)
    lines = [
        OBSERVATION_HEADER,
        f"Källa: {cot.callsign}",
        f"Tid: {local_time.strftime('%Y-%m-%dT%H:%M:%S')}",
        f"Position: {position}",
        f"Typ: {cot.cot_type} ({cot.affiliation})",
        f"UID: {cot.uid}",
    ]
    if cot.custom_report:
        lines.append("")
        lines.append(f"Bifogad rapport: {cot.custom_report_name}" if cot.custom_report_name else "Bifogad rapport:")
        lines.extend(f"{key}: {value}" for key, value in cot.custom_report.items())
    if cot.remarks.strip():
        lines.extend(["", cot.remarks.strip()])
    return "\n".join(lines)


def build_envelope(cot: InboundCot, group_name: str) -> dict[str, Any]:
    """Signal-shaped envelope so inbound CoT reuses the whole existing chain.

    An 8S report is reshaped into ``7S RAPPORT`` text so the seven_s pipeline
    writes a normal 7S file; anything else stays a ``TAK-OBSERVATION`` note.
    The sender is the operator's device when the CoT names one, so notes group
    per operator rather than per marker.
    """
    message = to_7s_message(cot) if is_8s_report(cot) else render_observation(cot)
    return {
        "envelope": {
            "sourceName": cot.operator_callsign or cot.callsign,
            "sourceNumber": f"tak:{cot.sender_id}",
            "sourceUuid": f"tak:{cot.sender_id}",
            "timestamp": int(cot.event_time.timestamp() * 1000),
            "_source": "tak",
            "dataMessage": {
                "message": message,
                "groupV2": {"id": INBOUND_GROUP_ID, "name": group_name},
                "attachments": [],
            },
        }
    }


_SUMMARY_EVERY_SECONDS = 30.0
# How many discarded types the summary names.
_TALLY_IN_SUMMARY = 4


def _describe_tally(tally: dict[str, int]) -> str:
    """The most common discarded types, for the periodic summary.

    Without this, a whitelist that never matches looks identical to a quiet
    server in the log: all you see is "N mottagna, N filtrerade". Naming what
    was thrown away is what tells you whether to widen inbound_types or to go
    looking further upstream.
    """
    if not tally:
        return ""
    top = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:_TALLY_IN_SUMMARY]
    listed = ", ".join(f"{cot_type} x{count}" for cot_type, count in top)
    more = " m.fl." if len(tally) > len(top) else ""
    return f" — bortfiltrerade typer: {listed}{more}"


async def run_tak_listener(bridge: Any) -> None:
    """Consume the bridge's rx queue until cancelled."""
    from datetime import datetime, timezone

    from oden.messages_db import STATUS_QUEUED, create_raw_message, update_message_status
    from oden.pipeline_orchestrator import PipelineOrchestrator

    settings = {**_INBOUND_DEFAULTS, **bridge.settings}
    group_name = str(settings["inbound_group_name"]).strip() or "TAK Inkommande"
    restored = load_seen(cfg.CONFIG_DB)
    if restored:
        logger.info("TAK: minns %d tidigare sedda markörer — de importeras inte igen", len(restored))
    filt = InboundFilter(settings, seen=restored)
    tally: dict[str, int] = {}

    def persist_seen() -> None:
        """Save only when something changed, so a quiet server writes nothing."""
        if filt.seen_dirty:
            save_seen(filt.seen_snapshot(), cfg.CONFIG_DB)
            filt.seen_dirty = False

    orchestrator = PipelineOrchestrator(cfg.CONFIG_DB)
    last_summary = time.monotonic()

    logger.info("TAK: lyssnar på inkommande CoT (typer: %s)", ", ".join(filt.types) or "alla")
    while True:
        try:
            data = await bridge.rx_queue.get()
        except asyncio.CancelledError:
            persist_seen()  # a clean stop must not throw away what this run learned
            raise
        try:
            bridge.rx_total += 1
            bridge.last_rx_at = datetime.now(timezone.utc)
            prescreened = filt.prescreen_rejects(data)
            cot = None if prescreened else cot_to_inbound(data)

            if cot is None:
                bridge.rx_filtered += 1
                # The type is the one thing you need when the whitelist never matches,
                # so name it even for an event that never became an InboundCot.
                raw_type = raw_event_type(data)
                _count(tally, raw_type or "okänd typ")
                logger.debug(
                    "TAK: ignorerar CoT typ=%s — %s",
                    raw_type or "okänd",
                    "utanför inbound_types" if prescreened else "ingen användbar position",
                )
            elif not filt.accept(cot):
                bridge.rx_filtered += 1
                _count(tally, cot.cot_type)
                logger.debug("TAK: filtrerade CoT %s (%s) — %s", cot.uid, cot.cot_type, filt.last_reject)
            else:
                bridge.received_count += 1
                msg_data = build_envelope(cot, group_name)
                message_id = create_raw_message(cfg.CONFIG_DB, cfg.SIGNAL_NUMBER, msg_data)
                update_message_status(cfg.CONFIG_DB, message_id, STATUS_QUEUED)
                logger.info("TAK: inkommande CoT %s (%s) → not i '%s'", cot.uid, cot.cot_type, group_name)
                # ponytail: no Signal reader/writer for TAK-sourced messages — they carry
                # no attachments and no quote, the only things the pipelines use them for.
                await orchestrator.run_message(message_id=message_id, msg_data=msg_data, reader=None, writer=None)

            now = time.monotonic()
            if now - last_summary >= _SUMMARY_EVERY_SECONDS and bridge.rx_total:
                logger.info(
                    "TAK inkommande hittills: %d mottagna, %d filtrerade, %d noter skapade%s",
                    bridge.rx_total,
                    bridge.rx_filtered,
                    bridge.received_count,
                    _describe_tally(tally),
                )
                tally.clear()  # the tally describes the window, the counters the session
                last_summary = now
                persist_seen()
        except asyncio.CancelledError:
            persist_seen()
            raise
        except Exception as exc:
            logger.warning("TAK: kunde inte hantera inkommande CoT: %r", exc)


def start_tak_listener(bridge: Any) -> asyncio.Task[None] | None:
    """Start the listener task if inbound is enabled. Returns the task, or None."""
    settings = {**_INBOUND_DEFAULTS, **bridge.settings}
    if not settings.get("inbound_enabled"):
        logger.info("TAK: inkommande CoT är avstängt (inbound_enabled = false) — inga noter skapas")
        return None
    if bridge.rx_queue is None:
        logger.error("TAK: inkommande är aktiverat men bryggan har ingen rx-kö")
        return None
    return asyncio.create_task(run_tak_listener(bridge))


async def stop_tak_listener(task: asyncio.Task[None] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
