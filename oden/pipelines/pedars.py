"""PEDARS pipeline for structured maintenance reports."""

from __future__ import annotations

from typing import Any

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

_TOP_LEVEL_REQUIRED_FIELDS = {"till", "fran", "tnr"}

_LABEL_ALIASES = {
    "till": "till",
    "fran": "fran",
    "från": "fran",
    "tnr": "tnr",
    "totalt": "totalt",
    "itjanst": "i_tjanst",
    "itjänst": "i_tjanst",
    "skavara": "ska_vara",
    "avvikelser": "avvikelser",
}

_SECTION_ALIASES = {
    "ppersonal": "personal",
    "eersattningavfornodenheter": "ersattning",
    "ddrivmedel": "drivmedel",
    "aammunition": "ammunition",
    "rreparationer": "reparationer",
    "ssamladformaga": "samlad_formaga",
}

_DRIVMEDEL_ALIASES = {
    "fordon": "fordon",
    "elverk": "elverk",
    "lampor": "lampor_belysning",
    "belysning": "lampor_belysning",
    "lamporbelysning": "lampor_belysning",
    "ved": "ved_kaminer",
    "kaminer": "ved_kaminer",
    "vedkaminer": "ved_kaminer",
    "vedkamin": "ved_kaminer",
}

_STATUS_PREFIXES = {
    "gron": "Grön",
    "gul": "Gul",
    "rod": "Röd",
}


def _normalize_field(label: str) -> str:
    return normalize_label(label, _LABEL_ALIASES)


def _normalize_section_heading(line: str) -> str:
    return _SECTION_ALIASES.get(normalize_label(line), "")


def _normalize_drivmedel_heading(line: str) -> str:
    stripped = line.strip()
    if stripped.endswith(":"):
        stripped = stripped[:-1]
    return _DRIVMEDEL_ALIASES.get(normalize_label(stripped), "")


def _parse_personal(lines: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {"counts": {}, "avvikelser": [], "notes": []}
    collecting_avvikelser = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("-"):
            data["avvikelser"].append(stripped[1:].strip())
            collecting_avvikelser = True
            continue

        handled_any = False
        for part in [segment.strip() for segment in stripped.split("|") if segment.strip()]:
            if ":" not in part:
                continue
            label, value = part.split(":", 1)
            key = _normalize_field(label)
            value = value.strip()
            if key in {"totalt", "i_tjanst", "ska_vara"}:
                data["counts"][key] = value
                handled_any = True
                collecting_avvikelser = False
            elif key == "avvikelser":
                collecting_avvikelser = True
                handled_any = True
                if value:
                    data["avvikelser"].append(value)

        if handled_any:
            continue

        if collecting_avvikelser:
            data["avvikelser"].append(stripped)
        else:
            data["notes"].append(stripped)

    return data


def _parse_drivmedel(lines: list[str]) -> dict[str, list[str]]:
    data: dict[str, list[str]] = {
        "fordon": [],
        "elverk": [],
        "lampor_belysning": [],
        "ved_kaminer": [],
        "ovrigt": [],
    }
    current = "ovrigt"

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        heading = _normalize_drivmedel_heading(stripped)
        if heading:
            current = heading
            continue
        data[current].append(stripped.lstrip("- ").strip())

    return data


def _parse_plain_list(lines: list[str]) -> list[str]:
    return [line.strip().lstrip("- ").strip() for line in lines if line.strip()]


def _parse_samlad_formaga(lines: list[str]) -> dict[str, str]:
    stripped_lines = [line.strip() for line in lines if line.strip()]
    if not stripped_lines:
        raise ValueError("PEDARS report missing required samlad_formaga content")

    first_line = stripped_lines[0]
    normalized = normalize_label(first_line)
    status = ""
    for prefix, display in _STATUS_PREFIXES.items():
        if normalized.startswith(prefix):
            status = display
            break
    if not status:
        raise ValueError("PEDARS samlad_formaga must start with Grön, Gul, or Röd")

    return {
        "status": status,
        "status_line": first_line,
        "notes": "\n".join(stripped_lines[1:]).strip(),
    }


def is_pedars_message(message_text: str | None) -> bool:
    return is_structured_report_message(
        message_text,
        (
            "PEDARS – UNDERHÅLLSRAPPORT",
            "PEDARS - UNDERHÅLLSRAPPORT",
            "PEDARS UNDERHÅLLSRAPPORT",
            "PEDARS",
        ),
    )


def parse_pedars_report(message_text: str) -> dict[str, Any]:
    lines = iter_nonempty_lines(message_text)
    if not lines or not is_pedars_message(lines[0]):
        raise ValueError("Not a PEDARS report")

    first_section_index = find_first_matching_line(lines[1:], _normalize_section_heading)
    section_start = first_section_index + 1 if first_section_index is not None else len(lines)
    fields = parse_labeled_fields(
        lines[1:section_start],
        required_fields=_TOP_LEVEL_REQUIRED_FIELDS,
        optional_fields=set(),
        normalize=_normalize_field,
        error_prefix="PEDARS report",
    )

    section_blocks: dict[str, list[str]] = {}
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
        section_blocks[section_name] = section_lines

    required_sections = {"personal", "ersattning", "drivmedel", "ammunition", "reparationer", "samlad_formaga"}
    missing_sections = sorted(required_sections - set(section_blocks.keys()))
    if missing_sections:
        raise ValueError(f"PEDARS report missing required sections: {', '.join(missing_sections)}")

    fields.update(
        {
            "personal": _parse_personal(section_blocks["personal"]),
            "ersattning": "\n".join(line.strip() for line in section_blocks["ersattning"] if line.strip()).strip(),
            "drivmedel": _parse_drivmedel(section_blocks["drivmedel"]),
            "ammunition": _parse_plain_list(section_blocks["ammunition"]),
            "reparationer": _parse_plain_list(section_blocks["reparationer"]),
            "samlad_formaga": _parse_samlad_formaga(section_blocks["samlad_formaga"]),
        }
    )
    return fields


class PedarsPipeline(StructuredReportPipeline):
    """Structured pipeline that parses and stores PEDARS reports."""

    name = "pedars"
    display_name = "PEDARS – UNDERHÅLLSRAPPORT-pipeline"
    description = "Parserar strukturerade PEDARS-underhållsrapporter och sparar dem som separat rapportfil."
    selection_criteria = "Körs när första icke-tomma raden i meddelandet börjar med 'PEDARS'."
    header_prefixes = (
        "PEDARS – UNDERHÅLLSRAPPORT",
        "PEDARS - UNDERHÅLLSRAPPORT",
        "PEDARS UNDERHÅLLSRAPPORT",
        "PEDARS",
    )
    report_id_prefix = "PEDARS"
    report_type = "PEDARS-rapport"

    def parse_report(self, message_text: str) -> dict[str, Any]:
        return parse_pedars_report(message_text)

    def render_report(self, context: StructuredReportContext) -> str:
        fields = context.fields
        personal = fields["personal"]
        drivmedel = fields["drivmedel"]
        samlad_formaga = fields["samlad_formaga"]

        frontmatter_lines = build_base_frontmatter(
            report_id_prefix=self.report_id_prefix,
            report_type=self.report_type,
            context=context,
            extra_fields=[
                f"till: {build_base_frontmatter.__globals__['yaml_quote'](fields['till'].strip())}",
                f"fran: {build_base_frontmatter.__globals__['yaml_quote'](fields['fran'].strip())}",
                f"samlad_formaga: {build_base_frontmatter.__globals__['yaml_quote'](samlad_formaga['status'])}",
            ],
        )

        body_lines = [
            f"**Till:** {fields['till'].strip()}",
            "",
            f"**Från:** {fields['fran'].strip()}",
            "",
            f"**TNR:** {context.resolved_tnr}",
            "",
            "## P – PERSONAL",
            "",
        ]

        counts = personal["counts"]
        if "totalt" in counts:
            body_lines.extend([f"**Totalt:** {counts['totalt']}", ""])
        if "ska_vara" in counts:
            body_lines.extend([f"**Ska vara:** {counts['ska_vara']}", ""])
        if "i_tjanst" in counts:
            body_lines.extend([f"**I tjänst:** {counts['i_tjanst']}", ""])
        if personal["avvikelser"]:
            body_lines.extend(["**Avvikelser:**", ""])
            body_lines.extend([f"- {item}" for item in personal["avvikelser"]])
            body_lines.append("")
        body_lines.extend([f"{item}" for item in personal["notes"]])
        if personal["notes"]:
            body_lines.append("")

        body_lines.extend(
            [
                "## E – ERSÄTTNING AV FÖRNÖDENHETER",
                "",
                fields["ersattning"] or "-",
                "",
                "## D – DRIVMEDEL",
                "",
            ]
        )

        subsection_titles = {
            "fordon": "Fordon",
            "elverk": "Elverk",
            "lampor_belysning": "Lampor / Belysning",
            "ved_kaminer": "Ved / Kaminer",
            "ovrigt": "Övrigt",
        }
        for key in ["fordon", "elverk", "lampor_belysning", "ved_kaminer", "ovrigt"]:
            if not drivmedel[key]:
                continue
            body_lines.extend([f"### {subsection_titles[key]}", ""])
            body_lines.extend([f"- {item}" for item in drivmedel[key]])
            body_lines.append("")

        body_lines.extend(["## A – AMMUNITION", ""])
        body_lines.extend([f"- {item}" for item in fields["ammunition"]])
        body_lines.append("")
        body_lines.extend(["## R – REPARATIONER", ""])
        body_lines.extend([f"- {item}" for item in fields["reparationer"]])
        body_lines.append("")
        body_lines.extend(
            [
                "## S – SAMLAD FÖRMÅGA",
                "",
                samlad_formaga["status_line"],
                "",
            ]
        )
        if samlad_formaga["notes"]:
            body_lines.extend([samlad_formaga["notes"], ""])
        body_lines.extend(["SLUT!", ""])
        return "\n".join(frontmatter_lines + body_lines)
