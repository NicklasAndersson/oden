"""SCRIM pipeline — vehicle descriptions from ATAK into their own note type.

SCRIM (Storlek, Colour, Registrering, Identifierande kännetecken, Märke) is the
vehicle form the HV Rapporter plugin family files alongside an 8S. Unlike an 8S
it is not a 7S in disguise, so it gets its own ``typ`` rather than being folded
into one.

The point of the note type is the registration: it is written as a ``[[PLÅT]]``
link in exactly the canonical form :mod:`oden.pipelines.seven_s` uses, so a plate
seen here and a plate seen in a 7S resolve to the same node. Oden emits the link
and nothing more — building and enriching the entity note itself belongs to the
analysis step, see docs/FORMAT_SPEC.md §6.6.
"""

from __future__ import annotations

import logging

from oden.pipelines.seven_s import _extract_location, _link_remaining_plates
from oden.pipelines.structured_report import (
    StructuredReportContext,
    StructuredReportPipeline,
    build_base_frontmatter,
    is_structured_report_message,
    iter_nonempty_lines,
    normalize_label,
    parse_labeled_fields,
    resolve_report_datetime,
    trailing_obsidian_comment,
)
from oden.tak.scrim import SCRIM_HEADER, canonical_plate

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = {"tnr", "stund"}
_OPTIONAL_FIELDS = {"stalle", "storlek", "farg", "registrering", "kannetecken", "marke", "sagesman", "anmarkning"}

_LABEL_ALIASES = {
    "tnr": "tnr",
    "stund": "stund",
    "stalle": "stalle",
    "storlek": "storlek",
    "farg": "farg",
    "registrering": "registrering",
    "regnr": "registrering",
    "kannetecken": "kannetecken",
    "marke": "marke",
    "markemodell": "marke",
    "sagesman": "sagesman",
    "anmarkning": "anmarkning",
}

# At least one of the five SCRIM letters must have a value, so a bare header line
# cannot produce an empty note.
_DESCRIPTIVE_FIELDS = ("storlek", "farg", "registrering", "kannetecken", "marke")

_NO_PLATE_DISPLAY = "–"  # en dash: "looked, no plate" is an observation, not an omission


def _normalize_label(label: str) -> str:
    return normalize_label(label, _LABEL_ALIASES)


def is_scrim_message(message_text: str | None) -> bool:
    return is_structured_report_message(message_text, (SCRIM_HEADER,))


def parse_scrim_report(message_text: str) -> dict[str, str]:
    """Parse a ``SCRIM RAPPORT`` message into canonical field keys."""
    lines = iter_nonempty_lines(message_text)
    fields = parse_labeled_fields(
        lines[1:],
        required_fields=_REQUIRED_FIELDS,
        optional_fields=_OPTIONAL_FIELDS,
        normalize=_normalize_label,
        error_prefix="SCRIM",
    )
    if not any(fields.get(name, "").strip() for name in _DESCRIPTIVE_FIELDS):
        raise ValueError("SCRIM report has no vehicle description fields")
    return fields


class ScrimPipeline(StructuredReportPipeline):
    """Writes ``SCRIM RAPPORT`` messages as SCRIM notes in the vault."""

    name = "scrim"
    display_name = "SCRIM-pipeline"
    description = "Skriver SCRIM-fordonsbeskrivningar som egna noter och länkar registreringsnumret"
    selection_criteria = "Meddelanden som börjar med 'SCRIM RAPPORT'"

    header_prefixes = (SCRIM_HEADER,)
    report_id_prefix = "SCRIM"
    report_type = "SCRIM-rapport"
    tnr_field_name = "tnr"
    time_field_label = "Stund"

    def parse_report(self, message_text: str) -> dict[str, str]:
        return parse_scrim_report(message_text)

    def build_report_datetime(self, *, fields, reference_dt):
        """The observation time from ``Stund``, not the TNR.

        Same reason as 7S: reports are relayed by hand, so the arrival time is
        wrong by the relay delay — three months, in a real capture.
        """
        return resolve_report_datetime(
            fields["stund"].strip(),
            reference_dt,
            field_label=self.time_field_label,
        )

    def render_report(self, context: StructuredReportContext) -> str:
        fields = context.fields
        stalle_raw = fields.get("stalle", "").strip()
        plats, lat, lon = _extract_location(stalle_raw) if stalle_raw else ("", None, None)
        plate = canonical_plate(fields.get("registrering", ""))

        quote = build_base_frontmatter.__globals__["yaml_quote"]
        extra_fields: list[str] = []
        if plats:
            extra_fields.append(f"plats: {quote(plats)}")
        if lat is not None and lon is not None:
            lat_str, lon_str = f"{lat:.5f}", f"{lon:.5f}"
            extra_fields += [f"lat: {lat_str}", f"lon: {lon_str}", f"location: {quote(f'{lat_str},{lon_str}')}"]
        if plate:
            extra_fields.append(f"regnr: {quote(plate)}")
        sagesman = fields.get("sagesman", "").strip().upper()
        if sagesman:
            extra_fields.append(f"sagesman: {sagesman}")

        frontmatter_lines = build_base_frontmatter(
            report_id_prefix=self.report_id_prefix,
            report_type=self.report_type,
            context=context,
            extra_fields=extra_fields,
        )

        body_lines = [f"**TNR:** {context.resolved_tnr}", "", f"**Stund:** {fields['stund'].strip()}"]
        if stalle_raw:
            body_lines += ["", f"**Ställe:** {stalle_raw}"]
        for label, key in (("Storlek", "storlek"), ("Färg", "farg")):
            value = fields.get(key, "").strip()
            if value:
                body_lines += ["", f"**{label}:** {value}"]

        # Always rendered; the link is what ties this note to the vehicle's entity node.
        body_lines += ["", f"**Registrering:** {f'[[{plate}]]' if plate else _NO_PLATE_DISPLAY}"]
        if fields.get("registrering", "").strip() and plate is None:
            self._warn_non_canonical_plate(fields["registrering"].strip())

        for label, key, link in (
            ("Kännetecken", "kannetecken", True),
            # Not Märke: FORMAT_SPEC §6.2 — make/model alone is context, not an identifier.
            ("Märke/modell", "marke", False),
            ("Sagesman", "sagesman", False),
            ("Anmärkning", "anmarkning", True),
        ):
            value = fields.get(key, "").strip()
            if value:
                body_lines += ["", f"**{label}:** {_link_remaining_plates(value) if link else value}"]

        content = "\n".join(frontmatter_lines) + "\n" + "\n".join(body_lines) + "\n"
        comment = trailing_obsidian_comment(context.envelope.get("dataMessage", {}).get("message", ""))
        return content + f"\n{comment}\n" if comment else content

    def _warn_non_canonical_plate(self, value: str) -> None:
        """A registration we could not canonicalise is kept as text, not silently dropped."""
        self.last_warnings.append(
            {
                "field": "registrering",
                "value": value,
                "message": "SCRIM registration is not a usable plate; not linked",
            }
        )
        logger.warning("SCRIM registration is not a usable plate (%r); not linked", value)
