"""7S special pipeline for structured reports.

Matches messages starting with "7S RAPPORT" and writes a structured markdown
entry. Non-matching messages are skipped so downstream pipelines can process.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import mgrs

from oden.app_state import get_app_state
from oden.link_formatter import apply_regex_links
from oden.pipelines.structured_report import (
    StructuredReportContext,
    StructuredReportPipeline,
    build_base_frontmatter,
    is_structured_report_message,
    iter_nonempty_lines,
    normalize_label,
    parse_labeled_fields,
    resolve_report_datetime,
)

logger = logging.getLogger(__name__)

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
}

_OPTIONAL_FIELDS = {"sedan"}

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
_PARTIAL_PLATE_RE = re.compile(r"\b(?=[A-Z0-9.]*\.)([A-Z.]{3}[0-9.]{2}[0-9A-Z.])\b", re.IGNORECASE)


def _normalize_label(label: str) -> str:
    return normalize_label(label, _LABEL_ALIASES)


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


def _link_remaining_plates(text: str) -> str:
    def wrap_full(match: re.Match[str]) -> str:
        return f"[[{match.group(1).upper()}]]"

    def wrap_partial(match: re.Match[str]) -> str:
        return f"[[{match.group(1).upper()}]]"

    linked_segments: list[str] = []
    for segment in re.split(r"(\[\[[^\]]+\]\])", text):
        if not segment or segment.startswith("[["):
            linked_segments.append(segment)
            continue

        segment = _FULL_PLATE_RE.sub(wrap_full, segment)
        segment = _PARTIAL_PLATE_RE.sub(wrap_partial, segment)
        linked_segments.append(segment)

    return "".join(linked_segments)


def is_7s_message(message_text: str | None) -> bool:
    return is_structured_report_message(message_text, ("7S RAPPORT",))


def parse_7s_report(message_text: str) -> dict[str, str]:
    lines = iter_nonempty_lines(message_text)
    if not lines or not lines[0].upper().startswith("7S RAPPORT"):
        raise ValueError("Not a 7S report")
    return parse_labeled_fields(
        lines[1:],
        required_fields=_REQUIRED_FIELDS,
        optional_fields=_OPTIONAL_FIELDS,
        normalize=_normalize_label,
        error_prefix="7S report",
    )


class SevenSPipeline(StructuredReportPipeline):
    """Special pipeline that parses and stores 7S reports."""

    name = "seven_s"
    display_name = "7S RAPPORT-pipeline"
    description = "Parserar strukturerade 7S RAPPORT-meddelanden och sparar dem som separat rapportfil."
    selection_criteria = "Körs när första icke-tomma raden i meddelandet börjar med '7S RAPPORT'."
    header_prefixes = ("7S RAPPORT",)
    report_id_prefix = "7S"
    report_type = "7S-rapport"

    def _get_app_state(self) -> Any:
        return get_app_state()

    def parse_report(self, message_text: str) -> dict[str, str]:
        return parse_7s_report(message_text)

    def build_report_datetime(self, *, fields: dict[str, str], reference_dt: Any) -> Any:
        raw_tnr = fields["tnr"].strip()
        raw_stund = fields["stund"].strip()
        if not re.fullmatch(r"\d{6}", raw_tnr):
            raise ValueError("7S TNR must be DDHHMM")
        return resolve_report_datetime(raw_stund, reference_dt, field_label="7S Stund")

    def render_report(self, context: StructuredReportContext) -> str:
        fields = context.fields
        sagesman = fields["sagesman"].strip().upper()
        if not re.fullmatch(r"[A-E]Q", sagesman):
            warning = {
                "field": "sagesman",
                "value": sagesman,
                "message": "7S Sagesman is non-canonical; writing report anyway",
            }
            self.last_warnings.append(warning)
            logger.warning(
                "7S Sagesman is non-canonical (%r); writing report anyway",
                sagesman,
            )

        plats, lat, lon = _extract_location(fields["stalle"])
        stund_display = fields["stund"].strip()
        symbol_raw = fields["symbol"].strip()
        symbol = _link_remaining_plates(apply_regex_links(symbol_raw) or symbol_raw)

        extra_fields = [f"plats: {build_base_frontmatter.__globals__['yaml_quote'](plats)}"]
        if lat is not None and lon is not None:
            lat_str = f"{lat:.5f}"
            lon_str = f"{lon:.5f}"
            extra_fields.extend(
                [
                    f"lat: {lat_str}",
                    f"lon: {lon_str}",
                    f"location: {build_base_frontmatter.__globals__['yaml_quote'](f'{lat_str},{lon_str}')}",
                ]
            )
        extra_fields.append(f"sagesman: {sagesman}")

        frontmatter_lines = build_base_frontmatter(
            report_id_prefix=self.report_id_prefix,
            report_type=self.report_type,
            context=context,
            extra_fields=extra_fields,
        )

        body_lines = [
            f"**TNR:** {context.resolved_tnr}",
            "",
            f"**Stund:** {stund_display}",
            "",
            f"**Ställe:** {fields['stalle'].strip()}",
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

        sedan = fields.get("sedan", "").strip()
        if sedan:
            body_lines.extend([f"**Sedan:** {sedan}", ""])

        return "\n".join(frontmatter_lines + body_lines)
