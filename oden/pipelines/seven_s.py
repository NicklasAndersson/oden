"""7S special pipeline for structured reports.

Matches messages starting with "7S RAPPORT" and writes a structured markdown
entry. Non-matching messages are skipped so downstream pipelines can process.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import unicodedata
import uuid
from typing import Any

import mgrs

from oden import config as cfg
from oden.app_state import get_app_state
from oden.formatting import get_safe_group_dir_path
from oden.link_formatter import apply_regex_links

_REQUIRED_FIELDS = {
    "till",
    "fran",
    "tnr",
    "stund",
    "stalle",
    "styrka",
    "slag",
    "sysselsattning",
    "symbol",
    "sagesman",
    "sedan",
}

_LABEL_ALIASES = {
    "till": "till",
    "fran": "fran",
    "från": "fran",
    "tnr": "tnr",
    "stund": "stund",
    "stalle": "stalle",
    "ställe": "stalle",
    "styrka": "styrka",
    "slag": "slag",
    "sysselsattning": "sysselsattning",
    "sysselsättning": "sysselsattning",
    "symbol": "symbol",
    "sagesman": "sagesman",
    "sagesmän": "sagesman",
    "sedan": "sedan",
}

_PLATE_ALPHABET = "ABCDEFGHJKLMNPRSTUWXYZ"
_FULL_PLATE_RE = re.compile(rf"\b([{_PLATE_ALPHABET}]{{3}}[0-9]{{2}}[0-9{_PLATE_ALPHABET}])\b", re.IGNORECASE)
_PARTIAL_PLATE_RE = re.compile(r"\b([A-Z.]{3}[0-9.]{2}[0-9A-Z.])\b", re.IGNORECASE)


def _normalize_label(label: str) -> str:
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return _LABEL_ALIASES.get(text, text)


def _yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _extract_location(stalle: str) -> tuple[str, float | None, float | None]:
    """Extract place text and optional decimal coordinates from Ställe."""
    if "," not in stalle:
        return stalle.strip(), None, None

    parts = stalle.split(",", 1)
    mgrs_str = parts[0].strip()
    address = parts[1].strip() if len(parts) > 1 else ""

    lat = None
    lon = None
    try:
        m = mgrs.MGRS()
        lat, lon = m.toLatLon(mgrs_str)
    except Exception as e:
        logging.getLogger(__name__).debug(f"Failed to convert MGRS '{mgrs_str}' to coordinates: {e}")

    return address or stalle.strip(), lat, lon


def _resolve_observation_datetime(stund: str, reference_dt: datetime.datetime) -> datetime.datetime:
    if not re.fullmatch(r"\d{6}", stund):
        raise ValueError("7S Stund must be DDHHMM")

    day = int(stund[0:2])
    hour = int(stund[2:4])
    minute = int(stund[4:6])

    try:
        candidate = reference_dt.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError as exc:
        raise ValueError("7S Stund is not a valid local date/time") from exc

    if candidate > reference_dt:
        year = reference_dt.year
        month = reference_dt.month - 1
        if month == 0:
            month = 12
            year -= 1
        try:
            candidate = candidate.replace(year=year, month=month)
        except ValueError as exc:
            raise ValueError("7S Stund is not a valid local date/time") from exc

    return candidate


def _link_remaining_plates(text: str) -> str:
    def wrap_full(match: re.Match[str]) -> str:
        return f"[[{match.group(1).upper()}]]"

    def wrap_partial(match: re.Match[str]) -> str:
        plate = match.group(1).upper()
        if "." not in plate:
            return plate
        return f"[[{plate}]]"

    linked_segments: list[str] = []
    for segment in re.split(r"(\[\[[^\]]+\]\])", text):
        if not segment or segment.startswith("[["):
            linked_segments.append(segment)
            continue

        segment = _FULL_PLATE_RE.sub(wrap_full, segment)
        segment = _PARTIAL_PLATE_RE.sub(wrap_partial, segment)
        linked_segments.append(segment)

    return "".join(linked_segments)


def _link_symbol_text(text: str) -> str:
    linked = apply_regex_links(text) or text
    return _link_remaining_plates(linked)


def _build_7s_filepath(group_title: str, tnr_base: str) -> tuple[str, str]:
    group_dir = get_safe_group_dir_path(group_title)
    os.makedirs(group_dir, exist_ok=True)

    tnr = tnr_base
    counter = 2
    while True:
        filename = f"TNR{tnr}.md"
        filepath = os.path.join(group_dir, filename)
        if not os.path.exists(filepath):
            return filepath, tnr
        tnr = f"{tnr_base}_{counter}"
        counter += 1


def is_7s_message(message_text: str | None) -> bool:
    if not message_text:
        return False
    for line in message_text.splitlines():
        if line.strip():
            return line.strip().upper().startswith("7S RAPPORT")
    return False


def parse_7s_report(message_text: str) -> dict[str, str]:
    lines = [line.strip() for line in message_text.splitlines() if line.strip()]
    if not lines or not lines[0].upper().startswith("7S RAPPORT"):
        raise ValueError("Not a 7S report")

    fields: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        key = _normalize_label(label)
        if key in _REQUIRED_FIELDS:
            fields[key] = value.strip()

    missing = sorted(_REQUIRED_FIELDS - set(fields.keys()))
    if missing:
        raise ValueError(f"7S report missing required fields: {', '.join(missing)}")

    return fields


def _extract_message_details(envelope: dict[str, Any]) -> tuple[str | None, str | None, str | None, int]:
    dm = envelope.get("dataMessage") or {}
    group_meta = dm.get("groupV2") or dm.get("group") or dm.get("groupInfo") or {}
    timestamp = envelope.get("timestamp") or 0
    return (
        dm.get("message") or dm.get("body"),
        group_meta.get("name") or group_meta.get("title") or group_meta.get("groupName"),
        group_meta.get("id") or group_meta.get("groupId"),
        int(timestamp) if isinstance(timestamp, int | float) else 0,
    )


class SevenSPipeline:
    """Special pipeline that parses and stores 7S reports."""

    name = "seven_s"
    display_name = "7S RAPPORT-pipeline"
    description = "Parserar strukturerade 7S RAPPORT-meddelanden och sparar dem som separat rapportfil."
    selection_criteria = "Körs när första icke-tomma raden i meddelandet börjar med '7S RAPPORT'."

    async def run(
        self,
        *,
        msg_data: dict[str, Any],
        reader: Any,
        writer: Any,
    ) -> bool:
        del reader, writer  # Not used by this pipeline currently.

        envelope = msg_data.get("envelope", {})
        if not envelope:
            return False

        if "syncMessage" in envelope and "dataMessage" not in envelope:
            return False

        message_text, group_title, group_id, timestamp_ms = _extract_message_details(envelope)
        if not is_7s_message(message_text):
            return False

        fields = parse_7s_report(message_text or "")

        source_name = envelope.get("sourceName")
        source_number = envelope.get("sourceNumber") or envelope.get("source")
        source_name = get_app_state().resolve_contact_name(source_number, source_name)

        dt = (
            datetime.datetime.fromtimestamp(timestamp_ms / 1000, tz=cfg.TIMEZONE)
            if timestamp_ms
            else datetime.datetime.now(cfg.TIMEZONE)
        )

        raw_tnr = fields["tnr"].strip()
        raw_stund = fields["stund"].strip()
        if not re.fullmatch(r"\d{6}", raw_tnr):
            raise ValueError("7S TNR must be DDHHMM")
        if raw_tnr != raw_stund:
            raise ValueError("7S TNR and Stund must match")

        sagesman = fields["sagesman"].strip().upper()
        if not re.fullmatch(r"[A-E]Q", sagesman):
            raise ValueError("7S Sagesman must match schema pattern [A-E]Q")

        observation_dt = _resolve_observation_datetime(raw_stund, dt)
        resolved_tnr = observation_dt.strftime("%d%H%M")

        resolved_group_title = group_title or "inbox"
        filepath, resolved_tnr = _build_7s_filepath(resolved_group_title, resolved_tnr)

        plats, lat, lon = _extract_location(fields["stalle"])
        tidpunkt = observation_dt.strftime("%Y-%m-%dT%H:%M:%S")
        stund_display = observation_dt.strftime("%Y-%m-%d %H:%M")
        symbol = _link_symbol_text(fields["symbol"].strip())

        frontmatter_lines = [
            "---",
            f"id: 7S-{uuid.uuid4()}",
            "typ: 7S-rapport",
            f"tnr: {_yaml_quote(resolved_tnr)}",
            f"tidpunkt: {_yaml_quote(tidpunkt)}",
            f"plats: {_yaml_quote(plats)}",
        ]
        if lat is not None and lon is not None:
            lat_str = f"{lat:.5f}"
            lon_str = f"{lon:.5f}"
            frontmatter_lines.extend(
                [
                    f"lat: {lat_str}",
                    f"lon: {lon_str}",
                    f"location: {_yaml_quote(f'{lat_str},{lon_str}')}",
                ]
            )
        frontmatter_lines.extend([f"sagesman: {sagesman}", "---", ""])

        body_lines = [
            f"**TNR:** {resolved_tnr}",
            "",
            f"**Stund:** {stund_display}",
            "",
            f"**Ställe:** {plats}",
            "",
            f"**Styrka:** {fields['styrka'].strip()}",
            "",
            f"**Slag:** {fields['slag'].strip()}",
            "",
            f"**Sysselsättning:** {fields['sysselsattning'].strip()}",
            "",
            f"**Symbol:** {symbol}",
            "",
            f"**Sagesman:** {sagesman}",
            "",
        ]

        content = "\n".join(frontmatter_lines + body_lines)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return True
