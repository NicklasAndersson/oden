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
from oden.pipelines.seven_s import _mgrs_to_latlon
from oden.tak.cot import InboundCot, distance_m, latlon_to_mgrs

# index -> Swedish month abbreviation, the reverse of structured_report._SWEDISH_MONTHS
_MONTHS_SV = ["JAN", "FEB", "MAR", "APR", "MAJ", "JUN", "JUL", "AUG", "SEP", "OKT", "NOV", "DEC"]

# The form pre-fills POSITION from the marker at 10 m grid precision (a 10 m cell
# is 14 m across the diagonal). Only a POSITION further away than that was edited
# by the operator and should override the exact CoT point.
_SAME_CELL_M = 20.0

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


def _stalle(cot: InboundCot, position: str) -> str:
    """7S ``Ställe`` from the 8S POSITION text and the CoT point.

    ``seven_s._extract_location`` reads coordinates from a bare MGRS or from
    ``"<MGRS>, <place>"``, so the grid always comes first and in compact form.
    """
    compact = "".join(position.split()).upper()
    operator_point = _mgrs_to_latlon(compact) if position else None
    if operator_point is not None and distance_m(*operator_point, cot.lat, cot.lon) > _SAME_CELL_M:
        return compact  # operator moved POSITION off the marker: their grid wins, CoT point stays in the raw block
    cot_mgrs = latlon_to_mgrs(cot.lat, cot.lon)
    if operator_point is not None or not position:
        return cot_mgrs or f"{cot.lat:.5f},{cot.lon:.5f}"  # a grid ref is not a place name: no "X, X"
    return f"{cot_mgrs}, {position}" if cot_mgrs else position  # prose place name (or no mgrs lib)


def to_7s_message(cot: InboundCot) -> str:
    """Render an 8S inbound CoT as a ``7S RAPPORT`` message the seven_s pipeline can parse."""
    report = cot.custom_report
    tnr, stund = _tnr_and_stund(cot)
    stalle = _stalle(cot, _field(report, _POSITION))

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
