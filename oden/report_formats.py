"""Rapportformat as settings: report formats defined in the GUI, not in code.

The built-in pipelines (7S, FORS, PEDARS, SCRIM) have hand-written parsers.
A format defined here is data: which header lines select it, which labelled
fields and which sections it has, which are required, which field is the TNR,
and optionally a Jinja template for the note body. Each format becomes a step
named ``format:<id>`` that a branch can contain like any built-in step, and it
writes one note per report exactly like the built-ins (same frontmatter base,
same file naming, same attachments, same Testruta).

Stored as the config key ``report_formats`` (a JSON list)::

    {
      "id": "fors-v2", "name": "FORS v2",
      "headers": ["FORS-RAPPORT"],
      "fields": [{"key": "till", "label": "Till", "aliases": [], "required": true, "type": "text"}],
      "sections": [{"key": "orientering", "label": "O – Orientering", "aliases": ["O"], "required": true}],
      "tnr_field": "tnr", "file_prefix": "FORS", "report_type": "FORS-rapport",
      "end_marker": "SLUT!", "template": ""
    }

Parsing, line by line after the header: ``Etikett: värde`` whose label (or an
alias) is a field sets that field; a line that is a section heading (or
``Rubrik: text``) starts that section; other lines belong to the current
section, or to *Övrigt* before the first section. ``end_marker`` stops it.
Labels are compared without case, accents, spaces or punctuation, so
``Förbandets position`` and ``FORBANDETS-POSITION`` are the same label.
"""

from __future__ import annotations

import datetime
import functools
import logging
import re
import uuid
from typing import Any

from oden import config as cfg
from oden.pipelines.structured_report import (
    StructuredReportContext,
    StructuredReportPipeline,
    build_base_frontmatter,
    iter_nonempty_lines,
    normalize_label,
    resolve_report_datetime,
    trailing_obsidian_comment,
    yaml_quote,
)

logger = logging.getLogger(__name__)

STEP_PREFIX = "format:"
FIELD_TYPES = ("text", "mgrs")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
# Frontmatter keys the base already writes; a field with one of these keys is body-only.
_RESERVED_KEYS = {"id", "typ", "tnr", "tidpunkt", "signal_tidpunkt", "signal_avsandare_nummer", "signal_avsandare_id"}
_MAX_TEMPLATE = 20000


def _slug(text: str, sep: str = "-") -> str:
    base = text.lower().translate(str.maketrans("åäöé", "aaoe"))
    return re.sub(r"[^a-z0-9]+", sep, base).strip(sep)


def _clean_list(value: Any, limit: int = 20) -> list[str]:
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.append(text)
    return seen[:limit]


def _normalize_items(raw: Any, kind: str, taken: set[str], *, with_type: bool) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{kind} måste vara en lista")
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"Varje {kind[:-2].lower() or kind} måste vara ett objekt")
        label = str(entry.get("label") or "").strip()
        if not label:
            raise ValueError(f"{kind}: varje rad behöver en etikett")
        key = str(entry.get("key") or "").strip() or _slug(label, "_")[:40]
        if not key or not key[0].isalpha():
            key = f"f_{key}"[:40]
        if not _KEY_RE.match(key):
            raise ValueError(f"{kind}: ogiltig nyckel {key!r} (a–z, 0–9, _)")
        if key in taken:
            raise ValueError(f"Nyckeln {key!r} används två gånger")
        taken.add(key)
        item: dict[str, Any] = {
            "key": key,
            "label": label[:80],
            "aliases": _clean_list(entry.get("aliases")),
            "required": bool(entry.get("required")),
        }
        if with_type:
            item["type"] = entry.get("type") if entry.get("type") in FIELD_TYPES else "text"
        items.append(item)
    return items


def normalize_format(value: Any, taken_ids: set[str] | None = None) -> dict[str, Any]:
    """Validate one format definition. Raises ValueError with a Swedish message."""
    from oden.template_loader import validate_template

    if not isinstance(value, dict):
        raise ValueError("Formatet måste vara ett objekt")
    taken_ids = taken_ids or set()
    name = str(value.get("name") or "").strip()
    if not name:
        raise ValueError("Formatet behöver ett namn")
    format_id = str(value.get("id") or "").strip() or _slug(name)[:32] or "format"
    if not value.get("id"):
        base, n = format_id, 2
        while format_id in taken_ids:
            format_id, n = f"{base}-{n}", n + 1
    if not _ID_RE.match(format_id):
        raise ValueError(f"Ogiltigt format-id: {format_id!r}")
    if format_id in taken_ids:
        raise ValueError(f"Det finns redan ett format med id {format_id!r}")

    headers = _clean_list(value.get("headers"), 10)
    if not headers:
        raise ValueError("Ange minst en rubrikrad som formatet känns igen på")

    keys: set[str] = set()
    fields = _normalize_items(value.get("fields"), "Fält", keys, with_type=True)
    sections = _normalize_items(value.get("sections"), "Avsnitt", keys, with_type=False)
    if not fields and not sections:
        raise ValueError("Formatet behöver minst ett fält eller avsnitt")

    tnr_field = str(value.get("tnr_field") or "").strip()
    if tnr_field and tnr_field not in {f["key"] for f in fields}:
        raise ValueError("TNR-fältet måste vara ett av formatets fält")

    file_prefix = str(value.get("file_prefix") or "").strip() or re.sub(r"[^A-Za-z0-9_-]", "", name.upper())[:20]
    if not _PREFIX_RE.match(file_prefix or ""):
        raise ValueError("Filprefixet får bara innehålla A–Z, 0–9, - och _ (högst 20 tecken)")

    template = str(value.get("template") or "")
    if len(template) > _MAX_TEMPLATE:
        raise ValueError("Mallen är för lång")
    if template.strip():
        ok, error = validate_template(template)
        if not ok:
            raise ValueError(f"Mallen: {error}")
        try:
            _template_env().from_string(template)  # unknown filters show up here, not at parse
        except Exception as exc:  # jinja2.TemplateError and friends
            raise ValueError(f"Mallen: {exc}") from exc

    return {
        "id": format_id,
        "name": name[:60],
        "headers": headers,
        "fields": fields,
        "sections": sections,
        "tnr_field": tnr_field,
        "file_prefix": file_prefix,
        "report_type": str(value.get("report_type") or "").strip()[:60] or f"{name[:50]}-rapport",
        "end_marker": str(value.get("end_marker") or "").strip()[:40],
        "template": template,
    }


def normalize_formats(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Rapportformaten måste vara en lista")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in value:
        fmt = normalize_format(raw, ids)
        ids.add(fmt["id"])
        result.append(fmt)
    return result


def load_formats(config_module: Any = cfg) -> list[dict[str, Any]]:
    """The stored formats; an invalid one is skipped (and logged), never fatal."""
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in getattr(config_module, "REPORT_FORMATS", None) or []:
        try:
            fmt = normalize_format(raw, ids)
        except ValueError as exc:
            logger.warning("Rapportformat hoppas över: %s", exc)
            continue
        ids.add(fmt["id"])
        result.append(fmt)
    return result


def step_name(format_id: str) -> str:
    return f"{STEP_PREFIX}{format_id}"


def is_format_step(name: str) -> bool:
    return isinstance(name, str) and name.startswith(STEP_PREFIX) and bool(_ID_RE.match(name[len(STEP_PREFIX) :]))


def pipeline_for(name: str, formats: list[dict[str, Any]] | None = None) -> FormatReportPipeline | None:
    """A fresh pipeline for step ``format:<id>``, or None if that format no longer exists."""
    if not is_format_step(name):
        return None
    format_id = name[len(STEP_PREFIX) :]
    for fmt in load_formats() if formats is None else formats:
        if fmt["id"] == format_id:
            return FormatReportPipeline(fmt)
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _lookup(items: list[dict[str, Any]]) -> dict[str, str]:
    table: dict[str, str] = {}
    for item in items:
        for label in [item["label"], item["key"], *item["aliases"]]:
            table.setdefault(normalize_label(label.rstrip(":")), item["key"])
    return table


def matches_header(fmt: dict[str, Any], message_text: str | None) -> bool:
    for line in (message_text or "").splitlines():
        if line.strip():
            first = line.strip().upper()
            return any(first.startswith(h.upper()) for h in fmt["headers"])
    return False


def parse(fmt: dict[str, Any], message_text: str) -> dict[str, Any]:
    """``{"fields", "sections", "other", "missing"}``; never raises on content."""
    lines = iter_nonempty_lines(message_text or "")
    field_of = _lookup(fmt["fields"])
    section_of = _lookup(fmt["sections"])
    end = normalize_label(fmt["end_marker"]) if fmt["end_marker"] else None

    fields: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    other: list[str] = []
    current: str | None = None
    for line in lines[1:]:
        normalized = normalize_label(line.rstrip(":"))
        if end and normalized == end:
            break
        if normalized in section_of:
            current = section_of[normalized]
            sections.setdefault(current, [])
            continue
        if ":" in line:
            label, value = line.split(":", 1)
            key = normalize_label(label)
            if key in field_of:
                fields[field_of[key]] = value.strip()
                continue
            if key in section_of:
                current = section_of[key]
                sections.setdefault(current, [])
                if value.strip():
                    sections[current].append(value.strip())
                continue
        (sections[current] if current else other).append(line)

    section_text = {key: "\n".join(body).strip() for key, body in sections.items()}
    missing = [f["label"] for f in fmt["fields"] if f["required"] and not fields.get(f["key"])]
    missing += [s["label"] for s in fmt["sections"] if s["required"] and not section_text.get(s["key"])]
    return {"fields": fields, "sections": section_text, "other": other, "missing": missing}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _mgrs_coords(value: str) -> tuple[str, str] | None:
    """``("59.33400", "18.06000")`` from an MGRS value (``"<MGRS>, <plats>"`` works too)."""
    from oden.pipelines.seven_s import _mgrs_to_latlon

    coords = _mgrs_to_latlon(value.split(",", 1)[0])
    return (f"{coords[0]:.5f}", f"{coords[1]:.5f}") if coords else None


def _mgrs_extra(value: str) -> list[str]:
    coords = _mgrs_coords(value)
    if coords is None:
        return []
    lat, lon = coords
    return [f"lat: {lat}", f"lon: {lon}", f"location: {yaml_quote(f'{lat},{lon}')}"]


def is_whole_file_template(template: str) -> bool:
    """A template starting with ``---`` writes the whole note, frontmatter included."""
    return template.lstrip().startswith("---")


def _plate(value: Any) -> str:
    from oden.tak.scrim import canonical_plate

    return canonical_plate(str(value or "")) or ""


def _link_plates(value: Any) -> str:
    from oden.pipelines.seven_s import _link_remaining_plates

    return _link_remaining_plates(str(value or ""))


@functools.lru_cache(maxsize=1)
def _template_env() -> Any:
    """The sandbox for report format templates, with the filters the built-ins use.

    ``yaml`` quotes a value for frontmatter, ``plate`` gives the canonical form
    of a registration (empty if it is not one) and ``link_plates`` wraps plates
    in text as ``[[…]]`` links — the same as 7S and SCRIM do.
    """
    from jinja2.sandbox import SandboxedEnvironment

    env = SandboxedEnvironment()
    env.filters.update(
        {"yaml": lambda v: yaml_quote("" if v is None else str(v)), "plate": _plate, "link_plates": _link_plates}
    )
    return env


class FormatReportPipeline(StructuredReportPipeline):
    """A report step built from a format definition instead of code."""

    def __init__(self, fmt: dict[str, Any]) -> None:
        self.format = fmt
        self.name = step_name(fmt["id"])
        self.display_name = fmt["name"]
        self.description = f"Rapportformat ”{fmt['name']}” (definierat i inställningarna)."
        self.selection_criteria = "Körs när första icke-tomma raden börjar med " + " eller ".join(
            f"'{h}'" for h in fmt["headers"]
        )
        self.header_prefixes = tuple(fmt["headers"])
        self.report_id_prefix = fmt["file_prefix"]
        self.file_prefix = fmt["file_prefix"]
        self.report_type = fmt["report_type"]
        self.tnr_field_name = fmt["tnr_field"] or "tnr"

    def matches_message(self, message_text: str | None) -> bool:
        return matches_header(self.format, message_text)

    def parse_report(self, message_text: str) -> dict[str, Any]:
        parsed = parse(self.format, message_text)
        if parsed["missing"]:
            raise ValueError(f"{self.format['name']} saknar obligatoriska fält: {', '.join(parsed['missing'])}")
        return {**parsed["fields"], "_parsed": parsed}

    def report_tnr(self, fields: dict[str, Any], reference_dt: datetime.datetime) -> str:
        # The TNR names the file; only keep characters that are safe in a file name.
        raw = str(fields.get(self.format["tnr_field"]) or "") if self.format["tnr_field"] else ""
        return re.sub(r"[^0-9A-Za-z_-]", "", raw)[:40] or reference_dt.strftime("%d%H%M")

    def build_report_datetime(self, *, fields: dict[str, Any], reference_dt: datetime.datetime) -> datetime.datetime:
        raw = str(fields.get(self.format["tnr_field"]) or "").strip() if self.format["tnr_field"] else ""
        if not raw:
            return reference_dt
        label = next(f["label"] for f in self.format["fields"] if f["key"] == self.format["tnr_field"])
        return resolve_report_datetime(raw, reference_dt, field_label=f"{self.format['name']} {label}")

    def render_report(self, context: StructuredReportContext) -> str:
        fmt = self.format
        parsed = context.fields["_parsed"]
        values, sections = parsed["fields"], parsed["sections"]

        extra: list[str] = []
        for field in fmt["fields"]:
            value = values.get(field["key"])
            if not value or field["key"] in _RESERVED_KEYS:
                continue
            extra.append(f"{field['key']}: {yaml_quote(value)}")
            if field["type"] == "mgrs" and not any(line.startswith("lat:") for line in extra):
                extra.extend(_mgrs_extra(value))
        frontmatter = build_base_frontmatter(
            report_id_prefix=self.report_id_prefix,
            report_type=self.report_type,
            context=context,
            extra_fields=extra,
        )

        raw_message = (context.envelope.get("dataMessage") or {}).get("message") or ""
        if is_whole_file_template(fmt["template"]):
            # The template writes the whole note, frontmatter included.
            report = self._render_template(context, values, sections, parsed["other"], raw_message).strip() + "\n"
        else:
            if fmt["template"].strip():
                body = self._render_template(context, values, sections, parsed["other"], raw_message)
            else:
                body = self._default_body(values, sections, parsed["other"])
            report = "\n".join(frontmatter) + body.rstrip() + "\n"
        comment = trailing_obsidian_comment(raw_message)
        return f"{report.rstrip()}\n\n{comment}\n" if comment else report

    def _default_body(self, values: dict[str, str], sections: dict[str, str], other: list[str]) -> str:
        lines: list[str] = []
        for field in self.format["fields"]:
            if values.get(field["key"]):
                lines.extend([f"**{field['label']}:** {values[field['key']]}", ""])
        for section in self.format["sections"]:
            if section["key"] in sections:
                lines.extend([f"## {section['label']}", "", sections[section["key"]] or "-", ""])
        if other:
            lines.extend(["## Övrigt", "", *other, ""])
        return "\n".join(lines)

    def _render_template(
        self,
        context: StructuredReportContext,
        values: dict[str, str],
        sections: dict[str, str],
        other: list[str],
        raw_message: str,
    ) -> str:
        lat = lon = None
        for field in self.format["fields"]:
            if field["type"] == "mgrs" and values.get(field["key"]):
                coords = _mgrs_coords(values[field["key"]])
                if coords:
                    lat, lon = coords
                    break
        template = _template_env().from_string(self.format["template"])
        return template.render(
            format=self.format["name"],
            fields=values,
            sections=sections,
            other="\n".join(other),
            id=f"{self.report_id_prefix}-{uuid.uuid4()}",
            report_type=self.report_type,
            tnr=context.resolved_tnr,
            report_time=context.report_dt.strftime("%Y-%m-%d %H:%M"),
            report_time_iso=context.report_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            signal_time=context.signal_dt.strftime("%Y-%m-%d %H:%M"),
            signal_time_iso=context.signal_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            sender_name=context.source_name or "",
            sender_number=context.source_number,
            sender_id=context.source_id,
            lat=lat,
            lon=lon,
            group=context.group_title,
            message=raw_message,
        )


# ---------------------------------------------------------------------------
# Starting points: the built-ins as editable definitions
# ---------------------------------------------------------------------------


def _f(label: str, *, key: str = "", required: bool = False, aliases: tuple[str, ...] = (), type_: str = "text"):
    return {"key": key, "label": label, "aliases": list(aliases), "required": required, "type": type_}


def _s(label: str, *, key: str, required: bool = False, aliases: tuple[str, ...] = ()):
    return {"key": key, "label": label, "aliases": list(aliases), "required": required}


# The same frontmatter the built-ins write (build_base_frontmatter), for templates
# that write the whole note.
_BASE_FRONTMATTER = """---
id: {{ id }}
typ: {{ report_type }}
tnr: {{ tnr | yaml }}
tidpunkt: {{ report_time_iso | yaml }}
signal_tidpunkt: {{ signal_time_iso | yaml }}
signal_avsandare_nummer: {{ sender_number | yaml }}
signal_avsandare_id: {{ sender_id | yaml }}
"""

_COORDS = """{% if lat %}lat: {{ lat }}
lon: {{ lon }}
location: {{ (lat ~ "," ~ lon) | yaml }}
{% endif %}"""

_TEMPLATE_7S = (
    _BASE_FRONTMATTER
    + """plats: {{ fields.stalle | yaml }}
"""
    + _COORDS
    + """sagesman: {{ fields.sagesman | upper }}
---

**TNR:** {{ tnr }}

**Stund:** {{ fields.stund }}

**Ställe:** {{ fields.stalle }}

{% if fields.handelse %}**Händelse:** {{ fields.handelse }}

{% else %}**Styrka:** {{ fields.styrka }}

**Slag:** {{ fields.slag }}

**Sysselsättning:** {{ fields.sysselsattning }}

{% endif %}{% if fields.symbol %}**Symbol:** {{ fields.symbol | link_plates }}

{% endif %}**Sagesman:** {{ fields.sagesman | upper }}
{% if fields.sedan %}
**Sedan:** {{ fields.sedan }}
{% endif %}"""
)

_TEMPLATE_FORS = (
    _BASE_FRONTMATTER
    + """---

**Till:** {{ fields.till }}

**Från:** {{ fields.fran }}

**TNR:** {{ tnr }}

## F – FÖRBANDETS POSITION

{{ sections.forbandets_position }}

## O – ORIENTERING

{{ sections.orientering }}

## R – REDOGÖRELSE FÖR VHT

**Genomförd:** {{ fields.genomford }}

**Pågående:** {{ fields.pagaende }}

**Planerad:** {{ fields.planerad }}
{% if sections.slutsatser %}
## S – SLUTSATSER

{{ sections.slutsatser }}
{% endif %}
SLUT!"""
)

_TEMPLATE_PEDARS = (
    _BASE_FRONTMATTER
    + """till: {{ fields.till | yaml }}
fran: {{ fields.fran | yaml }}
samlad_formaga: {{ ((sections.samlad_formaga or "").split() or [""])[0] | yaml }}
---
{%- macro bullets(text) %}
{%- for line in (text or "").split("\\n") if line.strip() %}
- {{ line.strip().lstrip("-").strip() }}
{%- endfor %}
{%- endmacro %}

**Till:** {{ fields.till }}

**Från:** {{ fields.fran }}

**TNR:** {{ tnr }}

## P – PERSONAL
{% for line in (sections.personal or "").split("\\n") if line.strip() %}
{%- for part in line.split("|") if ":" in part %}
**{{ part.split(":")[0].strip() }}:** {{ part.split(":", 1)[1].strip() }}
{% endfor %}
{%- if ":" not in line %}{{ line.strip() }}
{% endif %}
{%- endfor %}
## E – ERSÄTTNING AV FÖRNÖDENHETER

{{ sections.ersattning or "-" }}

## D – DRIVMEDEL
{% for line in (sections.drivmedel or "").split("\\n") if line.strip() %}
{%- if line.strip().endswith(":") %}
### {{ line.strip()[:-1] }}
{% else %}
- {{ line.strip().lstrip("-").strip() }}
{%- endif %}
{%- endfor %}

## A – AMMUNITION
{{ bullets(sections.ammunition) }}

## R – REPARATIONER
{{ bullets(sections.reparationer) }}

## S – SAMLAD FÖRMÅGA

{% set samlad = (sections.samlad_formaga or "").split("\\n", 1) -%}
{{ samlad[0] }}
{% if samlad | length > 1 %}
{{ samlad[1] }}
{% endif %}
SLUT!"""
)

_TEMPLATE_SCRIM = (
    _BASE_FRONTMATTER
    + """{% if fields.stalle %}plats: {{ fields.stalle | yaml }}
{% endif %}"""
    + _COORDS
    + """{% if fields.registrering | plate %}regnr: {{ fields.registrering | plate | yaml }}
{% endif %}{% if fields.sagesman %}sagesman: {{ fields.sagesman | upper }}
{% endif %}---

**TNR:** {{ tnr }}

**Stund:** {{ fields.stund }}
{% if fields.stalle %}
**Ställe:** {{ fields.stalle }}
{% endif %}{% if fields.storlek %}
**Storlek:** {{ fields.storlek }}
{% endif %}{% if fields.farg %}
**Färg:** {{ fields.farg }}
{% endif %}
**Registrering:** {% if fields.registrering | plate %}[[{{ fields.registrering | plate }}]]{% else %}–{% endif %}
{% if fields.kannetecken %}
**Kännetecken:** {{ fields.kannetecken | link_plates }}
{% endif %}{% if fields.marke %}
**Märke/modell:** {{ fields.marke }}
{% endif %}{% if fields.sagesman %}
**Sagesman:** {{ fields.sagesman }}
{% endif %}{% if fields.anmarkning %}
**Anmärkning:** {{ fields.anmarkning | link_plates }}
{% endif %}"""
)


STARTERS: dict[str, dict[str, Any]] = {
    "seven_s": {
        "name": "7S (eget)",
        "headers": ["7S RAPPORT"],
        "fields": [
            _f("Till", required=True),
            _f("Från", key="fran", required=True),
            _f("TNR", key="tnr", required=True),
            _f("Stund", required=True),
            _f("Ställe", key="stalle", required=True, type_="mgrs"),
            _f("Styrka"),
            _f("Slag"),
            _f("Sysselsättning", key="sysselsattning"),
            _f("Symbol"),
            _f("Händelse", key="handelse"),
            _f("Sagesman", required=True, aliases=("Sagesmän",)),
            _f("Sedan"),
        ],
        "sections": [],
        "tnr_field": "tnr",
        "file_prefix": "TNR",
        "report_type": "7S-rapport",
        "template": _TEMPLATE_7S,
    },
    "fors": {
        "name": "FORS (eget)",
        "headers": ["FORS-RAPPORT", "FORS RAPPORT"],
        "fields": [
            _f("Till", required=True),
            _f("Från", key="fran", required=True),
            _f("TNR", key="tnr", required=True),
            _f("Genomförd", key="genomford", aliases=("Genomförd verksamhet",)),
            _f("Pågående", key="pagaende", aliases=("Pågående verksamhet",)),
            _f("Planerad", aliases=("Planerad verksamhet",)),
        ],
        "sections": [
            _s("F – Förbandets position", key="forbandets_position", required=True),
            _s("O – Orientering", key="orientering", required=True),
            _s("R – Redogörelse för vht", key="redogorelse", aliases=("R – Redogörelse för verksamhet",)),
            _s("S – Slutsatser", key="slutsatser"),
        ],
        "tnr_field": "tnr",
        "file_prefix": "FORS",
        "report_type": "FORS-rapport",
        "end_marker": "SLUT!",
        "template": _TEMPLATE_FORS,
    },
    "pedars": {
        "name": "PEDARS (eget)",
        "headers": ["PEDARS"],
        "fields": [
            _f("Till", required=True),
            _f("Från", key="fran", required=True),
            _f("TNR", key="tnr", required=True),
        ],
        "sections": [
            _s("P – Personal", key="personal", required=True),
            _s("E – Ersättning av förnödenheter", key="ersattning", required=True),
            _s("D – Drivmedel", key="drivmedel", required=True),
            _s("A – Ammunition", key="ammunition", required=True),
            _s("R – Reparationer", key="reparationer", required=True),
            _s("S – Samlad förmåga", key="samlad_formaga", required=True),
        ],
        "tnr_field": "tnr",
        "file_prefix": "PEDARS",
        "report_type": "PEDARS-rapport",
        "end_marker": "SLUT!",
        "template": _TEMPLATE_PEDARS,
    },
    "scrim": {
        "name": "SCRIM (eget)",
        "headers": ["SCRIM RAPPORT"],
        "fields": [
            _f("TNR", key="tnr", required=True),
            _f("Stund", required=True),
            _f("Ställe", key="stalle", type_="mgrs"),
            _f("Storlek"),
            _f("Färg", key="farg"),
            _f("Registrering", aliases=("Regnr",)),
            _f("Kännetecken", key="kannetecken"),
            _f("Märke", key="marke", aliases=("Märke/modell",)),
            _f("Sagesman"),
            _f("Anmärkning", key="anmarkning"),
        ],
        "sections": [],
        "tnr_field": "tnr",
        "file_prefix": "SCRIM",
        "report_type": "SCRIM-rapport",
        "template": _TEMPLATE_SCRIM,
    },
}
