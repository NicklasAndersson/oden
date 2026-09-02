"""Inbound ATAK 8S report -> ``7S RAPPORT`` text.

The HV 8S enemy-observation form (ATAK Reports plugin) is a 7S with fewer,
differently named fields. Reshaping it into a ``7S RAPPORT`` message lets the
existing ``seven_s`` pipeline write a standard 7S file that the Obsidian vault
plugin ingests unchanged — no new schema, no new note type.

Every 8S field is carried verbatim in a trailing Obsidian ``%%`` comment
(hidden in reading view) so nothing the operator typed is lost, and the exact
CoT point coordinates go there too since the 7S ``Ställe`` round-trips through
MGRS.
"""

from __future__ import annotations

import datetime as _dt

from oden import config as cfg
from oden.tak.cot import InboundCot, latlon_to_mgrs

# index -> Swedish month abbreviation, the reverse of structured_report._SWEDISH_MONTHS
_MONTHS_SV = ["JAN", "FEB", "MAR", "APR", "MAJ", "JUN", "JUL", "AUG", "SEP", "OKT", "NOV", "DEC"]

# Field keys as cot._parse_custom_report humanizes them (Title Case).
_POSITION = "Position"
_STRENGTH_TYPE = "Strength Type"
_SYMBOL = "Symbol"
_INFORMANT = "Informant"
_OCCUPATION = "Occupation"
_TIME = "Time"
_THEN = "Then"


def is_8s_report(cot: InboundCot) -> bool:
    """True when this inbound CoT carries an ATAK 8S report block."""
    return cot.custom_report_name.upper() == "8S" and bool(cot.custom_report)


def _field(report: dict[str, str], key: str) -> str:
    """One 8S value on one line — a newline in operator text must not become a new ``Label:`` line."""
    return " ".join((report.get(key) or "").split())


def _tnr_and_stund(cot: InboundCot) -> tuple[str, str]:
    """``(TNR 'DDHHMM', Stund 'DDHHMMZMÅNÅÅÅÅ')`` from the 8S Time field, else the CoT time."""
    raw = _field(cot.custom_report, _TIME)
    parsed: _dt.datetime | None = None
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            parsed = _dt.datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        parsed = cot.event_time.astimezone(cfg.TIMEZONE)
    tnr = parsed.strftime("%d%H%M")
    return tnr, f"{tnr}Z{_MONTHS_SV[parsed.month - 1]}{parsed.year}"


def to_7s_message(cot: InboundCot) -> str:
    """Render an 8S inbound CoT as a ``7S RAPPORT`` message the seven_s pipeline can parse."""
    report = cot.custom_report
    tnr, stund = _tnr_and_stund(cot)

    position_text = _field(report, _POSITION)
    mgrs = latlon_to_mgrs(cot.lat, cot.lon)
    # "<mgrs>, <text>" so seven_s._extract_location recovers coordinates for the frontmatter;
    # fall back to the operator's text (or bare lat/lon) if the mgrs lib is missing.
    stalle = f"{mgrs}, {position_text or mgrs}" if mgrs else (position_text or f"{cot.lat:.5f},{cot.lon:.5f}")

    handelse = ", ".join(part for part in (_field(report, _STRENGTH_TYPE), _field(report, _OCCUPATION)) if part) or "-"

    lines = [
        "7S RAPPORT",
        "Till: TAK",
        f"Från: {cot.callsign}",
        f"TNR: {tnr}",
        f"Stund: {stund}",
        f"Ställe: {stalle}",
        f"Händelse: {handelse}",
    ]
    symbol = _field(report, _SYMBOL)
    if symbol:
        lines.append(f"Symbol: {symbol}")
    lines.append(f"Sagesman: {_field(report, _INFORMANT) or cot.callsign}")
    then = _field(report, _THEN)
    if then:
        lines.append(f"Sedan: {then}")

    # Raw block keeps the original text; only "%%" is neutered so it can't close the comment early.
    raw = [f"{key}: {value.replace('%%', '% %')}" for key, value in report.items()]
    raw += [f"lat: {cot.lat}", f"lon: {cot.lon}", f"cot_uid: {cot.uid}", f"cot_typ: {cot.cot_type}"]
    comment = "%%\n8S (ATAK) rådata — oförändrad:\n" + "\n".join(raw) + "\n%%"

    return "\n".join(lines) + "\n\n" + comment
