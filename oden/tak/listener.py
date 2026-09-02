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
import math
import time
from dataclasses import dataclass
from typing import Any

from oden import config as cfg
from oden.tak.cot import UID_PREFIX, InboundCot, cot_to_inbound, cot_type_matches, latlon_to_mgrs
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


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine. Good enough for a "has it moved?" test."""
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _content_signature(cot: InboundCot) -> str:
    """Text used to detect an unchanged repeat — remarks plus any custom_report fields."""
    return cot.remarks + "|" + str(sorted(cot.custom_report.items()))


@dataclass
class _Seen:
    lat: float
    lon: float
    signature: str  # remarks + custom_report fields, used to detect an unchanged repeat
    cot_type: str


class InboundFilter:
    """Decides whether one inbound CoT is worth a note. Pure, so it is testable."""

    def __init__(self, settings: dict[str, Any]) -> None:
        merged = {**_INBOUND_DEFAULTS, **settings}
        self.types = _as_list(merged["inbound_types"])
        self.allow = [c.lower() for c in _as_list(merged["inbound_callsign_allow"])]
        self.deny = [c.lower() for c in _as_list(merged["inbound_callsign_deny"])]
        self.min_move_m = _num(merged["inbound_min_move_m"], 100.0)
        self.max_per_minute = int(_num(merged["inbound_max_per_minute"], 60.0))
        self._seen: dict[str, _Seen] = {}
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

    def accept(self, cot: InboundCot, *, now: float | None = None) -> bool:
        if cot.uid.startswith(UID_PREFIX):
            self.last_reject = "egen markör (eko)"
            return False
        if self.types and not cot_type_matches(cot.cot_type, self.types):
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
        current = _Seen(cot.lat, cot.lon, _content_signature(cot), cot.cot_type)
        if previous is not None:
            unchanged = (
                previous.cot_type == current.cot_type
                and previous.signature == current.signature
                and _distance_m(previous.lat, previous.lon, current.lat, current.lon) < self.min_move_m
            )
            if unchanged:
                self.last_reject = "oförändrad sedan tidigare (dedup)"
                return False

        if len(self._seen) >= _SEEN_CAP:
            self._seen.clear()
        self._seen[cot.uid] = current  # record content even if rate-limiting drops this instance

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
    """
    message = to_7s_message(cot) if is_8s_report(cot) else render_observation(cot)
    return {
        "envelope": {
            "sourceName": cot.callsign,
            "sourceNumber": f"tak:{cot.uid}",
            "sourceUuid": f"tak:{cot.uid}",
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


async def run_tak_listener(bridge: Any) -> None:
    """Consume the bridge's rx queue until cancelled."""
    from datetime import datetime, timezone

    from oden.messages_db import STATUS_QUEUED, create_raw_message, update_message_status
    from oden.pipeline_orchestrator import PipelineOrchestrator

    settings = {**_INBOUND_DEFAULTS, **bridge.settings}
    group_name = str(settings["inbound_group_name"]).strip() or "TAK Inkommande"
    filt = InboundFilter(settings)
    orchestrator = PipelineOrchestrator(cfg.CONFIG_DB)
    last_summary = time.monotonic()

    logger.info("TAK: lyssnar på inkommande CoT (typer: %s)", ", ".join(filt.types) or "alla")
    while True:
        data = await bridge.rx_queue.get()
        try:
            bridge.rx_total += 1
            bridge.last_rx_at = datetime.now(timezone.utc)
            cot = cot_to_inbound(data)

            if cot is None:
                bridge.rx_filtered += 1
                logger.debug("TAK: CoT utan användbar position, ignoreras")
            elif not filt.accept(cot):
                bridge.rx_filtered += 1
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
                    "TAK inkommande hittills: %d mottagna, %d filtrerade, %d noter skapade",
                    bridge.rx_total,
                    bridge.rx_filtered,
                    bridge.received_count,
                )
                last_summary = now
        except asyncio.CancelledError:
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
