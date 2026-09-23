"""Inbound ATAK SCRIM report -> ``SCRIM RAPPORT`` text.

SCRIM is the vehicle-description form the HV Rapporter plugin family files
alongside an 8S: **S**torlek, **C**olour, **R**egistrering, **I**dentifierande
kännetecken, **M**ärke. Unlike an 8S it is not a 7S in disguise, so it becomes
its own note type rather than being folded into an existing one.

The text this module emits is **Oden's own canonical wire format**, not something
an operator writes by hand. It exists because ``PipelineOrchestrator.reprocess``
replays ``envelope_raw`` and nothing else — the CoT XML is never stored — so
anything that must survive a reprocess has to live inside the message body. A
side effect worth having: an operator *can* paste the same shape into Signal and
it parses.

Every field is carried verbatim in the trailing ``%%`` block as well, including
the free-text remarks, which is where operators put corrections
("Regnr rättning TOS99218 Polsk registrerad").
"""

from __future__ import annotations

import re

from oden import config as cfg
from oden.tak.cot import InboundCot, latlon_to_mgrs
from oden.tak.hv_fields import field_value, parse_local, raw_block, stalle, tnr_and_stund

SCRIM_HEADER = "SCRIM RAPPORT"

_SIZE = "size"
_COLOUR = "colour"
_REGISTRATION = "registration"
_MARKS = "marks"
_MAKE = "make"
_INFORMANT = "informant"
_POSITION = "position"
_TIME = "time"
_CREATED = "created"

# The single letters are the mnemonic the operator sees in ATAK; the spelled-out
# aliases are there because the same family has shipped Swedish element names for
# other forms and may yet for this one. normalize_key only strips punctuation, it
# does not truncate, so "S" and "SAGESMAN" stay distinct.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    _SIZE: ("S", "STORLEK", "SIZE", "STORLEKTYP"),
    _COLOUR: ("C", "FÄRG", "FARG", "COLOUR", "COLOR"),
    _REGISTRATION: ("R", "REG", "REGNR", "REGISTRERING", "REGISTRATION"),
    _MARKS: ("I", "KÄNNETECKEN", "KANNETECKEN", "SÄRDRAG", "SARDRAG", "IDENTIFYINGMARKS"),
    _MAKE: ("M", "MÄRKE", "MARKE", "MÄRKEMODELL", "MODELL", "MAKE", "MAKEMODEL"),
    _INFORMANT: ("SAGESMAN", "SÄGESMAN", "INFORMANT"),
    _POSITION: ("STÄLLE", "STALLE", "POSITION"),
    _TIME: ("STUND", "TID", "TIME"),
    _CREATED: ("SKAPAD", "CREATED"),
}

# What an operator writes when they looked and there was no plate to read. Worth
# distinguishing from an omitted field: "no plate" is an observation.
_NO_PLATE = {"", "-", "--", "---", "–", "—", "?", "??", "N/A", "NA", "SAKNAS", "OKÄND", "OKAND", "INGEN", "INGET"}

# A plate is wrapped in [[…]] unconditionally rather than by regex match, so the
# value has to be reduced to characters that cannot break out of a wikilink —
# "[", "]", "|", "#", "^" and newlines all would. seven_s._link_remaining_plates
# never needed this because it only ever wraps its own regex matches.
_PLATE_STRIP = re.compile(r"[^0-9A-ZÅÄÖ-]+")
_MAX_PLATE_LEN = 16


def is_scrim_report(cot: InboundCot) -> bool:
    """True when this inbound CoT carries a SCRIM block."""
    return cot.custom_report_name.upper() == "SCRIM" and bool(cot.custom_report)


def canonical_plate(raw: str) -> str | None:
    """A registration reduced to the form the vault links on, or None if it is not one.

    Upper-case and unspaced, so ``PHS 331`` becomes ``PHS331`` — byte-identical to
    what :func:`oden.pipelines.seven_s._link_remaining_plates` emits for the same
    plate seen in a 7S, which is what makes both reports resolve to one entity.

    Hyphens and the Swedish vowels are kept: foreign plates carry them, and
    folding them away would merge distinct vehicles.
    """
    cleaned = _PLATE_STRIP.sub("", "".join(raw.upper().split()))
    if not cleaned or raw.strip().upper() in _NO_PLATE:
        return None
    if len(cleaned) > _MAX_PLATE_LEN or not any(char.isdigit() for char in cleaned):
        return None  # a sentence typed into R, not a registration
    return cleaned


def _tnr_and_stund(cot: InboundCot) -> tuple[str, str, str]:
    """``(TNR, Stund, källa)`` — the observation time, not the time it reached us.

    Reports are relayed by hand through the chain of command, so the CoT event
    time is the *forward* time; in a real capture that was three months late.
    ``STUND`` is the truth, ``Skapad`` says the same instant as epoch ms, and the
    event time is the last resort. Which one was used goes in the raw block, so a
    wildly wrong TNR is diagnosable rather than mysterious.
    """
    report = cot.custom_report
    for source, raw in (
        ("STUND", field_value(report, _FIELD_ALIASES[_TIME])),
        ("Skapad", field_value(report, _FIELD_ALIASES[_CREATED])),
    ):
        parsed = parse_local(raw)
        if parsed is not None:
            return (*tnr_and_stund(parsed), source)
    return (*tnr_and_stund(cot.event_time.astimezone(cfg.TIMEZONE)), "event_time")


def to_scrim_message(cot: InboundCot) -> str:
    """Render a SCRIM inbound CoT as the ``SCRIM RAPPORT`` text the pipeline parses."""
    report = cot.custom_report
    tnr, stund, tnr_source = _tnr_and_stund(cot)

    position = field_value(report, _FIELD_ALIASES[_POSITION])
    # Without a position field, fall back to the marker's own point — a TAK-sourced
    # SCRIM always has one, since cot_to_inbound rejects an event without coordinates.
    stalle_text = stalle(cot, position) if position else (latlon_to_mgrs(cot.lat, cot.lon) or "")

    lines = [SCRIM_HEADER, f"TNR: {tnr}", f"Stund: {stund}"]
    if stalle_text:
        lines.append(f"Ställe: {stalle_text}")
    for label, field in (
        ("Storlek", _SIZE),
        ("Färg", _COLOUR),
        ("Registrering", _REGISTRATION),
        ("Kännetecken", _MARKS),
        ("Märke", _MAKE),
    ):
        value = field_value(report, _FIELD_ALIASES[field])
        # Registrering is always written, with a dash when there was none: on a
        # checklist "looked, no plate" is not the same as "field omitted".
        if value or field is _REGISTRATION:
            lines.append(f"{label}: {value or '-'}")
    # The marker label is "SCRIM-BRGB05-151345", so the sender is the fallback, not cot.callsign.
    lines.append(f"Sagesman: {field_value(report, _FIELD_ALIASES[_INFORMANT]) or cot.sender_callsign}")
    remarks = " ".join(cot.remarks.split())
    if remarks:
        lines.append(f"Anmärkning: {remarks}")

    return "\n".join(lines) + "\n\n" + raw_block(cot, "SCRIM", extra=[f"tnr_kalla: {tnr_source}"])
