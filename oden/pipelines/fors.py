"""FORS pipeline for structured activity reports."""

from __future__ import annotations

from typing import Any

from oden.app_state import get_app_state
from oden.pipelines.structured_report import (
    StructuredReportContext,
    StructuredReportPipeline,
    build_base_frontmatter,
    find_first_matching_line,
    is_structured_report_message,
    iter_nonempty_lines,
    normalize_label,
    parse_labeled_fields,
)

_TOP_LEVEL_REQUIRED_FIELDS = {"till", "fran", "tnr", "forbandets_position", "orientering"}
_TOP_LEVEL_OPTIONAL_FIELDS: set[str] = set()
_R_REQUIRED_FIELDS = {"genomford", "pagaende", "planerad"}

_LABEL_ALIASES = {
    "till": "till",
    "fran": "fran",
    "från": "fran",
    "tnr": "tnr",
    "genomford": "genomford",
    "genomförd": "genomford",
    "genomfordverksamhet": "genomford",
    "genomfördverksamhet": "genomford",
    "pagaende": "pagaende",
    "pågående": "pagaende",
    "pagaendeverksamhet": "pagaende",
    "pågåendeverksamhet": "pagaende",
    "planerad": "planerad",
    "planeradverksamhet": "planerad",
}

_SECTION_ALIASES = {
    "fforbandetsposition": "forbandets_position",
    "oorientering": "orientering",
    "rredogorelseforvht": "redogorelse_for_vht",
    "sslutsatser": "slutsatser",
}


def _normalize_label(label: str) -> str:
    return normalize_label(label, _LABEL_ALIASES)


def _normalize_section_heading(line: str) -> str:
    return _SECTION_ALIASES.get(normalize_label(line), "")


def is_fors_message(message_text: str | None) -> bool:
    return is_structured_report_message(message_text, ("FORS-RAPPORT", "FORS RAPPORT"))


def parse_fors_report(message_text: str) -> dict[str, str]:
    lines = iter_nonempty_lines(message_text)
    if not lines or not is_fors_message(lines[0]):
        raise ValueError("Not a FORS report")

    first_section_index = find_first_matching_line(lines[1:], _normalize_section_heading)
    section_start = first_section_index + 1 if first_section_index is not None else len(lines)

    fields = parse_labeled_fields(
        lines[1:section_start],
        required_fields={"till", "fran", "tnr"},
        optional_fields=_TOP_LEVEL_OPTIONAL_FIELDS,
        normalize=_normalize_label,
        error_prefix="FORS report",
    )

    index = section_start
    while index < len(lines):
        section_name = _normalize_section_heading(lines[index])
        if not section_name:
            index += 1
            continue

        index += 1
        section_lines: list[str] = []
        while index < len(lines):
            next_line = lines[index]
            if next_line.upper() == "SLUT!" or _normalize_section_heading(next_line):
                break
            section_lines.append(next_line)
            index += 1

        if section_name == "redogorelse_for_vht":
            r_fields = parse_labeled_fields(
                section_lines,
                required_fields=_R_REQUIRED_FIELDS,
                optional_fields=set(),
                normalize=_normalize_label,
                error_prefix="FORS report VHT",
            )
            fields.update(r_fields)
            continue

        fields[section_name] = "\n".join(section_lines).strip()

    missing = sorted((_TOP_LEVEL_REQUIRED_FIELDS | _R_REQUIRED_FIELDS) - set(fields.keys()))
    if missing:
        raise ValueError(f"FORS report missing required fields: {', '.join(missing)}")

    return fields


class ForsPipeline(StructuredReportPipeline):
    """Structured pipeline that parses and stores FORS reports."""

    name = "fors"
    display_name = "FORS-RAPPORT-pipeline"
    description = "Parserar strukturerade FORS-RAPPORT-meddelanden och sparar dem som separat rapportfil."
    selection_criteria = "Körs när första icke-tomma raden i meddelandet börjar med 'FORS-RAPPORT'."
    header_prefixes = ("FORS-RAPPORT", "FORS RAPPORT")
    report_id_prefix = "FORS"
    report_type = "FORS-rapport"

    def _get_app_state(self) -> Any:
        return get_app_state()

    def parse_report(self, message_text: str) -> dict[str, str]:
        return parse_fors_report(message_text)

    def render_report(self, context: StructuredReportContext) -> str:
        frontmatter_lines = build_base_frontmatter(
            report_id_prefix=self.report_id_prefix,
            report_type=self.report_type,
            context=context,
        )
        fields = context.fields
        body_lines = [
            f"**Till:** {fields['till'].strip()}",
            "",
            f"**Från:** {fields['fran'].strip()}",
            "",
            f"**TNR:** {context.resolved_tnr}",
            "",
            "## F – FÖRBANDETS POSITION",
            "",
            fields["forbandets_position"],
            "",
            "## O – ORIENTERING",
            "",
            fields["orientering"],
            "",
            "## R – REDOGÖRELSE FÖR VHT",
            "",
            f"**Genomförd:** {fields['genomford'].strip()}",
            "",
            f"**Pågående:** {fields['pagaende'].strip()}",
            "",
            f"**Planerad:** {fields['planerad'].strip()}",
            "",
        ]
        slutsatser = fields.get("slutsatser", "").strip()
        if slutsatser:
            body_lines.extend(
                [
                    "## S – SLUTSATSER",
                    "",
                    slutsatser,
                    "",
                ]
            )
        body_lines.extend(["SLUT!", ""])
        return "\n".join(frontmatter_lines + body_lines)
