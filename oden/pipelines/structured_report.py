"""Shared helpers for structured report pipelines."""

from __future__ import annotations

import datetime
import json
import os
import re
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from oden import config as cfg

_SHORT_REPORT_TIME_RE = re.compile(r"^\d{6}$")
_LONG_REPORT_TIME_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})([A-Z])([A-Z]{3})(\d{4})$")
_SWEDISH_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAJ": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OKT": 10,
    "NOV": 11,
    "DEC": 12,
}


def normalize_label(label: str, aliases: Mapping[str, str] | None = None) -> str:
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    if aliases:
        return aliases.get(text, text)
    return text


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def iter_nonempty_lines(message_text: str) -> list[str]:
    return [line.strip() for line in message_text.splitlines() if line.strip()]


def find_first_matching_line(lines: Sequence[str], matcher: Callable[[str], str]) -> int | None:
    for index, line in enumerate(lines):
        if matcher(line):
            return index
    return None


def is_structured_report_message(message_text: str | None, prefixes: Sequence[str]) -> bool:
    if not message_text:
        return False
    for line in message_text.splitlines():
        stripped = line.strip()
        if stripped:
            return any(stripped.upper().startswith(prefix.upper()) for prefix in prefixes)
    return False


def parse_labeled_fields(
    lines: Sequence[str],
    *,
    required_fields: set[str],
    optional_fields: set[str],
    normalize: Callable[[str], str],
    error_prefix: str,
) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines:
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        key = normalize(label)
        if key in required_fields or key in optional_fields:
            fields[key] = value.strip()

    missing = sorted(required_fields - set(fields.keys()))
    if missing:
        raise ValueError(f"{error_prefix} missing required fields: {', '.join(missing)}")

    return fields


def resolve_report_datetime(
    compact_time: str,
    reference_dt: datetime.datetime,
    *,
    field_label: str,
) -> datetime.datetime:
    if _SHORT_REPORT_TIME_RE.fullmatch(compact_time):
        day = int(compact_time[0:2])
        hour = int(compact_time[2:4])
        minute = int(compact_time[4:6])

        try:
            candidate = reference_dt.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError as exc:
            raise ValueError(f"{field_label} is not a valid local date/time") from exc

        if candidate > reference_dt:
            year = reference_dt.year
            month = reference_dt.month - 1
            if month == 0:
                month = 12
                year -= 1
            try:
                candidate = candidate.replace(year=year, month=month)
            except ValueError as exc:
                raise ValueError(f"{field_label} is not a valid local date/time") from exc

        return candidate

    long_match = _LONG_REPORT_TIME_RE.fullmatch(compact_time.upper())
    if not long_match:
        raise ValueError(f"{field_label} must be DDHHMM or DDHHMMZMÅNÅÅÅÅ")

    day = int(long_match.group(1))
    hour = int(long_match.group(2))
    minute = int(long_match.group(3))
    month = _SWEDISH_MONTHS.get(long_match.group(5))
    year = int(long_match.group(6))
    if month is None:
        raise ValueError(f"{field_label} has invalid month abbreviation")

    try:
        return datetime.datetime(year, month, day, hour, minute, tzinfo=reference_dt.tzinfo)
    except ValueError as exc:
        raise ValueError(f"{field_label} is not a valid local date/time") from exc


def build_report_filepath(vault_subdir: str | None, tnr_base: str, *, prefix: str = "TNR") -> tuple[str, str]:
    """Resolve a collision-free filepath inside the vault.

    If *vault_subdir* is a non-empty string the file is written to
    ``VAULT_PATH/<vault_subdir>/``.  When it is ``None`` or an empty string
    the file lands directly in the root of the vault.
    """
    if vault_subdir:
        # Sanitise: strip leading separator, reject traversal
        safe = os.path.normpath(vault_subdir).lstrip(os.sep)
        if ".." in safe.split(os.sep):
            raise ValueError(f"vault_subdir must not contain '..': {vault_subdir!r}")
        target_dir = os.path.join(cfg.VAULT_PATH, safe)
    else:
        target_dir = cfg.VAULT_PATH
    os.makedirs(target_dir, exist_ok=True)

    tnr = tnr_base
    counter = 2
    while True:
        filename = f"{prefix}{tnr}.md"
        filepath = os.path.join(target_dir, filename)
        if not os.path.exists(filepath):
            return filepath, tnr
        tnr = f"{tnr_base}_{counter}"
        counter += 1


def extract_message_details(envelope: dict[str, Any]) -> tuple[str | None, str | None, str | None, int]:
    dm = envelope.get("dataMessage") or {}
    group_meta = dm.get("groupV2") or dm.get("group") or dm.get("groupInfo") or {}
    timestamp = envelope.get("timestamp") or 0
    return (
        dm.get("message") or dm.get("body"),
        group_meta.get("name") or group_meta.get("title") or group_meta.get("groupName"),
        group_meta.get("id") or group_meta.get("groupId"),
        int(timestamp) if isinstance(timestamp, int | float) else 0,
    )


@dataclass(frozen=True)
class StructuredReportContext:
    fields: dict[str, Any]
    raw_tnr: str
    resolved_tnr: str
    report_dt: datetime.datetime
    signal_dt: datetime.datetime
    source_number: str
    source_id: str
    source_name: str | None
    group_title: str
    group_id: str | None
    envelope: dict[str, Any]


def build_base_frontmatter(
    *,
    report_id_prefix: str,
    report_type: str,
    context: StructuredReportContext,
    extra_fields: Sequence[str] | None = None,
) -> list[str]:
    lines = [
        "---",
        f"id: {report_id_prefix}-{uuid.uuid4()}",
        f"typ: {report_type}",
        f"tnr: {yaml_quote(context.resolved_tnr)}",
        f"tidpunkt: {yaml_quote(context.report_dt.strftime('%Y-%m-%dT%H:%M:%S'))}",
        f"signal_tidpunkt: {yaml_quote(context.signal_dt.strftime('%Y-%m-%dT%H:%M:%S'))}",
        f"signal_avsandare_nummer: {yaml_quote(context.source_number)}",
        f"signal_avsandare_id: {yaml_quote(context.source_id)}",
    ]
    if extra_fields:
        lines.extend(extra_fields)
    lines.extend(["---", ""])
    return lines


class StructuredReportPipeline:
    """Common run-loop for pipelines that write one markdown report file."""

    header_prefixes: tuple[str, ...] = ()
    report_id_prefix = "REPORT"
    report_type = "rapport"
    file_prefix = "TNR"
    tnr_field_name = "tnr"
    time_field_label = "TNR"
    #: Subdirectory under VAULT_PATH where reports are written.
    #: ``None`` (the default) means the vault root.
    #: Can be overridden per-pipeline via PIPELINE_SETTINGS[name]["vault_subdir"].
    vault_subdir: str | None = None

    def matches_message(self, message_text: str | None) -> bool:
        return is_structured_report_message(message_text, self.header_prefixes)

    def _get_app_state(self) -> Any:
        raise NotImplementedError

    def parse_report(self, message_text: str) -> dict[str, str]:
        raise NotImplementedError

    def build_report_datetime(
        self,
        *,
        fields: dict[str, Any],
        reference_dt: datetime.datetime,
    ) -> datetime.datetime:
        return resolve_report_datetime(
            fields[self.tnr_field_name].strip(),
            reference_dt,
            field_label=f"{self.report_id_prefix} {self.time_field_label}",
        )

    def render_report(self, context: StructuredReportContext) -> str:
        raise NotImplementedError

    async def run(
        self,
        *,
        msg_data: dict[str, Any],
        reader: Any,
        writer: Any,
    ) -> bool:
        del reader, writer
        self.last_warnings: list[dict[str, str]] = []

        envelope = msg_data.get("envelope", {})
        if not envelope:
            return False

        if "syncMessage" in envelope and "dataMessage" not in envelope:
            return False

        message_text, group_title, group_id, timestamp_ms = extract_message_details(envelope)
        if not self.matches_message(message_text):
            return False

        fields = self.parse_report(message_text or "")

        source_name = envelope.get("sourceName")
        source_number = envelope.get("sourceNumber") or envelope.get("source")
        source_name = self._get_app_state().resolve_contact_name(source_number, source_name)

        dt = (
            datetime.datetime.fromtimestamp(timestamp_ms / 1000, tz=cfg.TIMEZONE)
            if timestamp_ms
            else datetime.datetime.now(cfg.TIMEZONE)
        )
        signal_timestamp_ms = envelope.get("serverReceivedTimestamp") or timestamp_ms
        signal_dt = (
            datetime.datetime.fromtimestamp(signal_timestamp_ms / 1000, tz=cfg.TIMEZONE) if signal_timestamp_ms else dt
        )
        source_id = envelope.get("sourceUuid")
        if not source_number:
            raise ValueError(f"{self.report_id_prefix} Signal sender number is missing")
        if not source_id:
            raise ValueError(f"{self.report_id_prefix} Signal sender id is missing")

        raw_tnr = fields[self.tnr_field_name].strip()
        report_dt = self.build_report_datetime(fields=fields, reference_dt=dt)

        resolved_group_title = group_title or "inbox"

        # vault_subdir: per-pipeline settings win over class-level default
        pipeline_settings = cfg.PIPELINE_SETTINGS.get(self.name, {}) if isinstance(cfg.PIPELINE_SETTINGS, dict) else {}
        effective_vault_subdir = pipeline_settings.get("vault_subdir", self.vault_subdir)

        filepath, resolved_tnr = build_report_filepath(effective_vault_subdir, raw_tnr, prefix=self.file_prefix)

        content = self.render_report(
            StructuredReportContext(
                fields=fields,
                raw_tnr=raw_tnr,
                resolved_tnr=resolved_tnr,
                report_dt=report_dt,
                signal_dt=signal_dt,
                source_number=source_number,
                source_id=source_id,
                source_name=source_name,
                group_title=resolved_group_title,
                group_id=group_id,
                envelope=envelope,
            )
        )

        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write(content)

        return True
