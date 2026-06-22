"""7S special pipeline for structured reports.

Matches messages starting with "7S RAPPORT" and writes a structured markdown
entry. Non-matching messages are skipped so downstream pipelines can process.
"""

from __future__ import annotations

import datetime
import os
import re
import unicodedata
from typing import Any

from oden import config as cfg
from oden.app_state import get_app_state
from oden.formatting import format_sender_display, get_message_filepath

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


def _normalize_label(label: str) -> str:
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return _LABEL_ALIASES.get(text, text)


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

        resolved_group_title = group_title or "inbox"
        filepath = get_message_filepath(resolved_group_title, dt, source_name, source_number)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        sender_display = format_sender_display(source_name, source_number)
        timestamp_iso = dt.isoformat()

        content = (
            "---\n"
            "report_type: 7s\n"
            f"group_title: {resolved_group_title}\n"
            f"group_id: {group_id or ''}\n"
            f"timestamp: {timestamp_iso}\n"
            "---\n\n"
            "# 7S RAPPORT\n\n"
            f"- Till: {fields['till']}\n"
            f"- Från: {fields['fran']}\n"
            f"- TNR: {fields['tnr']}\n"
            f"- Stund: {fields['stund']}\n"
            f"- Ställe: {fields['stalle']}\n"
            f"- Styrka: {fields['styrka']}\n"
            f"- Slag: {fields['slag']}\n"
            f"- Sysselsättning: {fields['sysselsattning']}\n"
            f"- Symbol: {fields['symbol']}\n"
            f"- Sagesman: {fields['sagesman']}\n"
            f"- Sedan: {fields['sedan']}\n\n"
            "## Metadata\n\n"
            f"- Avsändare: {sender_display}\n"
            f"- Inkom: {timestamp_iso}\n"
        )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return True
