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

from oden import config as cfg
from oden.tak.cot import InboundCot
from oden.tak.hv_fields import field_value, parse_local, raw_block, stalle, tnr_and_stund

# Two different ATAK plugins both emit an 8S, and they disagree on everything but
# the block name. The "8S" plugin (com.atakmap.android.eights.plugin) flattens
# English keys into attributes; "HV Rapporter"
# (com.atakmap.android.hvreports.plugin) nests Swedish keys as element text. Both
# are enabled side by side across the fleet, so neither is "the" format.
#
# Rather than branch on which plugin sent it, every logical field lists the keys
# it can arrive under. Lookup is normalised (upper-case, punctuation stripped),
# which also absorbs the parser's own inconsistency: an attribute key is
# title-cased on the way in while an element tag keeps its raw casing.
_POSITION = "position"
_STRENGTH_TYPE = "strength_type"
_SYMBOL = "symbol"
_INFORMANT = "informant"
_OCCUPATION = "occupation"
_TIME = "time"
_THEN = "then"

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    _POSITION: ("POSITION", "STÄLLE", "STALLE"),
    _STRENGTH_TYPE: ("STRENGTHTYPE", "STYRKASLAG", "STYRKA"),
    _SYMBOL: ("SYMBOL",),
    _INFORMANT: ("INFORMANT", "SAGESMAN", "SÄGESMAN"),
    _OCCUPATION: ("OCCUPATION", "SYSSELSÄTTNING", "SYSSELSATTNING"),
    _TIME: ("TIME", "STUND", "TID"),
    _THEN: ("THEN", "SEDAN"),
}


def is_8s_report(cot: InboundCot) -> bool:
    """True when this inbound CoT carries an ATAK 8S report block."""
    return cot.custom_report_name.upper() == "8S" and bool(cot.custom_report)


def _field(report: dict[str, str], field: str) -> str:
    """One 8S value, looked up under whichever of its aliases the plugin used."""
    return field_value(report, _FIELD_ALIASES[field])


def _tnr_and_stund(cot: InboundCot) -> tuple[str, str]:
    """``(TNR 'DDHHMM', Stund 'DDHHMMZMÅNÅÅÅÅ')`` from the 8S Time field, else the CoT time."""
    parsed = parse_local(_field(cot.custom_report, _TIME))
    if parsed is None:
        parsed = cot.event_time.astimezone(cfg.TIMEZONE)
    return tnr_and_stund(parsed)


def to_7s_message(cot: InboundCot) -> str:
    """Render an 8S inbound CoT as a ``7S RAPPORT`` message the seven_s pipeline can parse."""
    report = cot.custom_report
    tnr, stund = _tnr_and_stund(cot)
    stalle_text = stalle(cot, _field(report, _POSITION))

    handelse = ", ".join(part for part in (_field(report, _STRENGTH_TYPE), _field(report, _OCCUPATION)) if part) or "-"

    lines = [
        "7S RAPPORT",
        "Till: TAK",
        f"Från: {cot.callsign}",
        f"TNR: {tnr}",
        f"Stund: {stund}",
        f"Ställe: {stalle_text}",
        f"Händelse: {handelse}",
    ]
    symbol = _field(report, _SYMBOL)
    if symbol:
        lines.append(f"Symbol: {symbol}")
    lines.append(f"Sagesman: {_field(report, _INFORMANT) or cot.callsign}")
    then = _field(report, _THEN)
    if then:
        lines.append(f"Sedan: {then}")

    return "\n".join(lines) + "\n\n" + raw_block(cot, "8S")
