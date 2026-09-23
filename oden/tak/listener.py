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

There is a *second* inbound path alongside the stream. An 8S sent from ATAK with
an attachment never appears on the CoT broadcast at all — ATAK packs the event and
the photo into a mission package and uploads it to the server's file store instead,
so listening to CoT loses the whole report, not just its image. When
``inbound_fetch_packages`` is on, :func:`run_package_poller` watches that store and
feeds the embedded CoT through this same filter and the same pipelines, so a report
looks identical in the vault whichever way it arrived. See :mod:`oden.tak.marti`.

See docs/PLAN_TAK.md phase 3.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import sqlite3
import time
from collections.abc import Sequence
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
    # a-x-X is exact, not a-x-*: it is what the "HV Rapporter" plugin files an 8S
    # under, and the rest of a-x-* is other things entirely.
    "inbound_types": ["a-f-G", "a-h-*", "a-n-G", "a-u-*", "a-x-X", "b-m-p-*", "b-a-*"],
    "inbound_callsign_allow": [],
    "inbound_callsign_deny": [],
    "inbound_min_move_m": 100.0,
    "inbound_max_per_minute": 60,
    "inbound_group_name": "TAK Inkommande",
    # Only notes for reports an operator filled in, never bare map markers.
    "inbound_reports_only": False,
    # An 8S sent *with* an attachment never reaches the CoT stream: ATAK uploads a
    # mission package to the server's file store instead. Off by default because
    # polling the store is outgoing traffic the operator has not asked for.
    "inbound_fetch_packages": False,
    "inbound_package_poll_seconds": 60,
    "marti_port": 8443,
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


# A plugin block that carries a single flag (``<targetmunitions visibility="true"/>``)
# is plumbing, not something an operator filled in. Two fields is the cheapest line
# that separates the two without hardcoding every plugin's tag name — the known-tag
# list in cot.py handles the ones we have actually seen.
_MIN_REPORT_FIELDS = 2


def has_structured_report(cot: InboundCot) -> bool:
    """True when the operator filled something in, rather than just dropping a marker.

    ``a-h-G`` cannot tell the two apart on its own: the "8S" plugin files its
    reports under exactly the same CoT type as any hand-placed hostile marker. So
    the report block is the only signal available.
    """
    if is_8s_report(cot):
        return True
    return len(cot.custom_report) >= _MIN_REPORT_FIELDS


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


def load_package_seen(db_path: Path) -> set[str]:
    """Hashes of mission packages already ingested.

    Without this every poll re-imports the whole archive — the file store keeps
    months of packages, and none of them are ever "new" again on their own.

    Never raises: a database error means an empty set, and the per-uid dedup in
    :class:`InboundFilter` still stops the re-imported events becoming notes.
    """
    try:
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            return {row[0] for row in conn.execute("SELECT hash FROM tak_package_seen")}
    except sqlite3.Error as exc:
        logger.warning("TAK: kunde inte läsa paketcachen (%s)", exc)
        return set()


def remember_package(db_path: Path, digest: str, name: str, submitted_at: str) -> None:
    """Record one package as taken. Written per package, not per batch, so an
    interrupted poll never re-imports what it already turned into notes."""
    try:
        with contextlib.closing(sqlite3.connect(db_path)) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO tak_package_seen (hash, name, submitted_at, seen_at) VALUES (?, ?, ?, ?)",
                (digest, name, submitted_at, time.time()),
            )
    except sqlite3.Error as exc:
        logger.warning("TAK: kunde inte spara paketcachen (%s)", exc)


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
        self.reports_only = bool(merged["inbound_reports_only"])
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

        # The *sender*, not the marker's own label. Matching the label only ever
        # worked by accident: "8S-LarsNo-312132" passed an allow-list of "R" on the
        # r in "LarsNo", while the same operator's "8S-AQEA01-121729" was blocked.
        sender = cot.sender_callsign
        lowered = sender.lower()
        if self.deny and any(d in lowered for d in self.deny):
            self.last_reject = f"avsändare {sender} på deny-listan"
            return False
        if self.allow and not any(a in lowered for a in self.allow):
            self.last_reject = f"avsändare {sender} inte på allow-listan"
            return False

        # Before dedup, so a marker that was never wanted does not take a slot in
        # the cache and then block a real report that later reuses the uid.
        if self.reports_only and not has_structured_report(cot):
            self.last_reject = f"{cot.cot_type} bär ingen ifylld rapport"
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


def build_envelope(
    cot: InboundCot,
    group_name: str,
    attachments: Sequence[tuple[str, bytes]] = (),
) -> dict[str, Any]:
    """Signal-shaped envelope so inbound CoT reuses the whole existing chain.

    An 8S report is reshaped into ``7S RAPPORT`` text so the seven_s pipeline
    writes a normal 7S file; anything else stays a ``TAK-OBSERVATION`` note.
    The sender is the operator's device when the CoT names one, so notes group
    per operator rather than per marker.

    ``attachments`` are ``(filename, bytes)`` from a mission package. They are
    base64-encoded into the shape ``attachment_handler.save_attachments`` already
    expects, so the vault write and the ``## Bilagor`` section need no TAK-specific
    code at all.
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
                "attachments": [
                    {"filename": name, "data": base64.b64encode(blob).decode("ascii")} for name, blob in attachments
                ],
            },
        }
    }


# The first poll comes quickly so a restart does not hide a fresh report for two
# intervals; long enough that the bridge has settled first.
_FIRST_POLL_DELAY = 5.0
# How far back an incremental query reaches beyond the newest thing seen.
# Absorbs out-of-order submissions and clock skew; re-seeing a package is free
# because the hash cache already knows it.
_POLL_OVERLAP_S = 600

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


async def _create_note(
    cot: InboundCot,
    group_name: str,
    orchestrator: Any,
    *,
    attachments: Sequence[tuple[str, bytes]] = (),
) -> None:
    """Turn one accepted CoT into a queued message and run it through the pipelines.

    Shared by the CoT stream and the mission-package poller so both paths produce
    byte-identical notes — the only difference between them is where the event came
    from, which is not something the vault should be able to tell.
    """
    from oden.messages_db import STATUS_QUEUED, create_raw_message, update_message_status

    msg_data = build_envelope(cot, group_name, attachments)
    message_id = create_raw_message(cfg.CONFIG_DB, cfg.SIGNAL_NUMBER, msg_data)
    update_message_status(cfg.CONFIG_DB, message_id, STATUS_QUEUED)
    # No Signal reader/writer: a TAK message carries no quote, and any attachment
    # it has is already inline as base64, so nothing needs fetching over JSON-RPC.
    await orchestrator.run_message(message_id=message_id, msg_data=msg_data, reader=None, writer=None)


async def run_package_poller(bridge: Any, *, filt: InboundFilter, group_name: str, orchestrator: Any) -> None:
    """Ingest mission packages from the Marti file store until cancelled.

    An 8S sent with an attachment never appears on the CoT stream, so without this
    the whole report is lost — not just its photo. See :mod:`oden.tak.marti`.

    The first round only *records* what is already in the archive. A TAK Server
    keeps months of packages, and importing several hundred old reports the first
    time inbound is switched on would bury the vault. Clearing ``tak_package_seen``
    is the deliberate way to ask for a backfill.
    """
    from tempfile import TemporaryDirectory

    from oden.tak import marti

    settings = {**_INBOUND_DEFAULTS, **bridge.settings}
    # A floor on the interval: this is someone else's server, and a tight loop over
    # a ~900-row archive is rude regardless of what the setting says.
    interval = max(15.0, _num(settings["inbound_package_poll_seconds"], 60.0))
    port = int(_num(settings["marti_port"], 8443.0))
    seen = load_package_seen(cfg.CONFIG_DB)

    with TemporaryDirectory(prefix="oden_marti_") as tmp:
        try:
            base_url = marti.marti_base_url(str(bridge.pytak_config.get("COT_URL") or ""), port)
            context = await asyncio.to_thread(marti.ssl_context, bridge.pytak_config, Path(tmp))
        except Exception as exc:
            logger.error("TAK: kan inte fråga filarkivet (%r) — paketpollningen startar inte", exc)
            return

        seeding = not seen
        incremental = await asyncio.to_thread(marti.supports_incremental, base_url, context)
        logger.info(
            "TAK: pollar filarkivet var %.0f s (%s)%s",
            interval,
            base_url,
            "" if incremental else " — servern stödjer inte startTime, hämtar hela listan varje gång",
        )

        first = True
        # The first round asks for everything: Oden may have been down for hours,
        # and a narrow window would step straight past what arrived meanwhile.
        full_sweep = True
        while True:
            # A short first wait so a restart does not hide a report for two full
            # intervals; after that, the configured pace.
            await asyncio.sleep(_FIRST_POLL_DELAY if first else interval)
            first = False
            try:
                since = ""
                if incremental and not seeding and not full_sweep:
                    # Reach back a whole extra round plus the overlap, so a poll that
                    # failed or ran late cannot leave a hole. Seeing the same package
                    # twice is free — the hash cache already knows it.
                    since = marti.utc_floor(int(interval * 2 + _POLL_OVERLAP_S))
                files = await asyncio.to_thread(marti.search, base_url, context, since=since)
                full_sweep = False
                fresh = [f for f in files if f.hash not in seen and f.looks_like_mission_package]

                if seeding:
                    for item in fresh:
                        remember_package(cfg.CONFIG_DB, item.hash, item.name, item.submitted_at)
                        seen.add(item.hash)
                    logger.info(
                        "TAK: filarkivet hade %d paket sedan tidigare — de importeras inte. "
                        "Nya paket hämtas från och med nu.",
                        len(fresh),
                    )
                    seeding = False
                    continue

                for item in fresh:
                    # Recorded before it is parsed: a package we cannot use must not
                    # come back every single round for the rest of the session.
                    seen.add(item.hash)
                    remember_package(cfg.CONFIG_DB, item.hash, item.name, item.submitted_at)

                    blob = await asyncio.to_thread(marti.fetch, base_url, item.hash, context)
                    if blob is None:
                        continue
                    package = await asyncio.to_thread(marti.unpack, blob)
                    if package is None:
                        logger.debug("TAK: %s är inget uppdragspaket med CoT — hoppar över", item.name)
                        continue

                    cot = cot_to_inbound(package.cot)
                    if cot is None:
                        logger.debug("TAK: CoT:en i %s gick inte att tolka", item.name)
                        continue

                    bridge.rx_total += 1
                    if not filt.accept(cot):
                        bridge.rx_filtered += 1
                        logger.debug("TAK: filtrerade paket-CoT %s — %s", cot.uid, filt.last_reject)
                        continue

                    bridge.received_count += 1
                    if package.skipped_empty:
                        logger.warning(
                            "TAK: %s deklarerar %d bilaga/bilagor som är 0 byte — ATAK packade dem tomma",
                            item.name,
                            package.skipped_empty,
                        )
                    logger.info(
                        "TAK: uppdragspaket %s (%s, %d bilaga/bilagor) → not i '%s'",
                        item.name,
                        cot.cot_type,
                        len(package.attachments),
                        group_name,
                    )
                    await _create_note(cot, group_name, orchestrator, attachments=package.attachments)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("TAK: paketpollningen misslyckades den här rundan (%r)", exc)


async def run_tak_listener(bridge: Any) -> None:
    """Consume the bridge's rx queue until cancelled, and poll the file store alongside."""
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

    # The file-store poller shares this run's filter, so a marker that arrived on
    # the stream is not imported a second time from a package.
    poller: asyncio.Task[None] | None = None
    if settings.get("inbound_fetch_packages"):
        poller = asyncio.create_task(
            run_package_poller(bridge, filt=filt, group_name=group_name, orchestrator=orchestrator)
        )

    logger.info("TAK: lyssnar på inkommande CoT (typer: %s)", ", ".join(filt.types) or "alla")
    try:
        await _consume_rx(bridge, filt, tally, group_name, orchestrator, persist_seen)
    finally:
        if poller is not None and not poller.done():
            poller.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poller


async def _consume_rx(
    bridge: Any,
    filt: InboundFilter,
    tally: dict[str, int],
    group_name: str,
    orchestrator: Any,
    persist_seen: Any,
) -> None:
    """The rx-queue loop proper, split out so the poller's cleanup has somewhere to hang."""
    from datetime import datetime, timezone

    last_summary = time.monotonic()
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
                logger.info("TAK: inkommande CoT %s (%s) → not i '%s'", cot.uid, cot.cot_type, group_name)
                await _create_note(cot, group_name, orchestrator)

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
