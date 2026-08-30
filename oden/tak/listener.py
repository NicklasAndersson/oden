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

logger = logging.getLogger(__name__)

INBOUND_GROUP_ID = "oden-tak-inbound"
OBSERVATION_HEADER = "TAK-OBSERVATION"  # deliberately not "... RAPPORT": must not re-parse as 7S

_INBOUND_DEFAULTS: dict[str, Any] = {
    "inbound_enabled": False,
    "inbound_types": ["a-h-*", "a-u-*", "b-a-*"],
    "inbound_callsign_allow": [],
    "inbound_callsign_deny": [],
    "inbound_min_move_m": 100.0,
    "inbound_max_per_minute": 60,
    "inbound_group_name": "TAK Inkommande",
}


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


@dataclass
class _Seen:
    lat: float
    lon: float
    remarks: str
    cot_type: str


class InboundFilter:
    """Decides whether one inbound CoT is worth a note. Pure, so it is testable."""

    def __init__(self, settings: dict[str, Any]) -> None:
        merged = {**_INBOUND_DEFAULTS, **settings}
        self.types = _as_list(merged["inbound_types"])
        self.allow = [c.lower() for c in _as_list(merged["inbound_callsign_allow"])]
        self.deny = [c.lower() for c in _as_list(merged["inbound_callsign_deny"])]
        self.min_move_m = float(merged["inbound_min_move_m"] or 0)
        self.max_per_minute = int(merged["inbound_max_per_minute"] or 0)
        self._seen: dict[str, _Seen] = {}
        self._window_start = 0.0
        self._window_count = 0

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
            return False  # our own marker echoed back
        if self.types and not cot_type_matches(cot.cot_type, self.types):
            return False

        callsign = cot.callsign.lower()
        if self.deny and any(d in callsign for d in self.deny):
            return False
        if self.allow and not any(a in callsign for a in self.allow):
            return False

        previous = self._seen.get(cot.uid)
        current = _Seen(cot.lat, cot.lon, cot.remarks, cot.cot_type)
        if previous is not None:
            unchanged = (
                previous.cot_type == current.cot_type
                and previous.remarks == current.remarks
                and _distance_m(previous.lat, previous.lon, current.lat, current.lon) < self.min_move_m
            )
            if unchanged:
                return False

        if self._rate_limited(time.monotonic() if now is None else now):
            logger.warning("TAK: fler än %s inkommande CoT/minut — släpper resten", self.max_per_minute)
            return False

        self._seen[cot.uid] = current
        return True


def render_observation(cot: InboundCot) -> str:
    """Human-readable note body. Must not look like a structured report header."""
    mgrs = latlon_to_mgrs(cot.lat, cot.lon)
    position = f"{mgrs} ({cot.lat:.5f}, {cot.lon:.5f})" if mgrs else f"{cot.lat:.5f}, {cot.lon:.5f}"
    lines = [
        OBSERVATION_HEADER,
        f"Källa: {cot.callsign}",
        f"Tid: {cot.event_time.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"Position: {position}",
        f"Typ: {cot.cot_type} ({cot.affiliation})",
        f"UID: {cot.uid}",
    ]
    if cot.remarks.strip():
        lines.extend(["", cot.remarks.strip()])
    return "\n".join(lines)


def build_envelope(cot: InboundCot, group_name: str) -> dict[str, Any]:
    """Signal-shaped envelope so inbound CoT reuses the whole existing chain."""
    return {
        "envelope": {
            "sourceName": cot.callsign,
            "sourceNumber": f"tak:{cot.uid}",
            "sourceUuid": f"tak:{cot.uid}",
            "timestamp": int(cot.event_time.timestamp() * 1000),
            "_source": "tak",
            "dataMessage": {
                "message": render_observation(cot),
                "groupV2": {"id": INBOUND_GROUP_ID, "name": group_name},
                "attachments": [],
            },
        }
    }


async def run_tak_listener(bridge: Any) -> None:
    """Consume the bridge's rx queue until cancelled."""
    from oden.messages_db import STATUS_QUEUED, create_raw_message, update_message_status
    from oden.pipeline_orchestrator import PipelineOrchestrator

    settings = {**_INBOUND_DEFAULTS, **bridge.settings}
    group_name = str(settings["inbound_group_name"])
    filt = InboundFilter(settings)
    orchestrator = PipelineOrchestrator(cfg.CONFIG_DB)
    received = 0

    logger.info("TAK: lyssnar på inkommande CoT (typer: %s)", ", ".join(filt.types) or "alla")
    while True:
        data = await bridge.rx_queue.get()
        try:
            cot = cot_to_inbound(data)
            if cot is None or not filt.accept(cot):
                continue

            received += 1
            bridge.received_count = received
            msg_data = build_envelope(cot, group_name)
            message_id = create_raw_message(cfg.CONFIG_DB, cfg.SIGNAL_NUMBER, msg_data)
            update_message_status(cfg.CONFIG_DB, message_id, STATUS_QUEUED)
            # ponytail: no Signal reader/writer for TAK-sourced messages — they carry
            # no attachments and no quote, the only things the pipelines use them for.
            await orchestrator.run_message(message_id=message_id, msg_data=msg_data, reader=None, writer=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("TAK: kunde inte hantera inkommande CoT: %r", exc)


def start_tak_listener(bridge: Any) -> asyncio.Task[None] | None:
    """Start the listener task if inbound is enabled. Returns the task, or None."""
    settings = {**_INBOUND_DEFAULTS, **bridge.settings}
    if not settings.get("inbound_enabled"):
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
