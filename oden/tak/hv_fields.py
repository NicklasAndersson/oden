"""Shared field plumbing for the ATAK "HV Rapporter" plugin family.

Several forms from the same family reach Oden as ``a-x-X`` CoT — 8S (enemy
observation), SCRIM (vehicle description), METHANE (casualty report) — and what
they share is their *conventions*, not their fields:

* keys are Swedish or single-letter mnemonics, and arrive title-cased when the
  plugin wrote them as XML attributes but raw-cased when it used element text;
* ``STUND`` is ISO 8601 in UTC while ``Skapad`` is the same instant as epoch
  milliseconds;
* ``STÄLLE`` is MGRS, pre-filled from the marker;
* newlines are double-escaped, so a literal ``&#10;`` lands in the value.

Keeping that here lets each reshaper differ only in its field table and its
output shape, rather than re-deriving the same quirks.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Iterable, Sequence

from oden import config as cfg
from oden.pipelines.seven_s import _mgrs_to_latlon
from oden.tak.cot import InboundCot, distance_m, latlon_to_mgrs

# index -> Swedish month abbreviation, the reverse of structured_report._SWEDISH_MONTHS
MONTHS_SV = ["JAN", "FEB", "MAR", "APR", "MAJ", "JUN", "JUL", "AUG", "SEP", "OKT", "NOV", "DEC"]

# The form pre-fills its position from the marker at 10 m grid precision (a 10 m
# cell is 14 m across the diagonal). Only a position further away than that was
# edited by the operator and should override the exact CoT point.
SAME_CELL_M = 20.0

# Whitespace character references only. The plugin double-escapes a newline, so
# ElementTree decodes one level and the five literal characters "&#10;" survive
# into the value. A general entity unescaper would be wrong here: "&amp;" and
# friends are already decoded, and a second pass would corrupt a literal "&".
_WS_CHAR_REF = re.compile(r"&#(?:9|10|13|x0?[9ADad]);")

# Epoch values outside this range are some other number that happens to be in a
# date-shaped field, not a timestamp.
_EPOCH_MIN_YEAR = 2000
_EPOCH_MAX_AHEAD = _dt.timedelta(days=366)


def normalize_key(key: str) -> str:
    """Key stripped to what identifies it: case, spaces and underscores carry no meaning."""
    return re.sub(r"[^0-9A-ZÅÄÖ]+", "", key.upper())


def unescape_char_refs(value: str) -> str:
    """Double-escaped whitespace references back to spaces.

    Deliberately a space rather than a real newline: every caller collapses
    whitespace immediately anyway, and turning operator text back into multiple
    lines would create a state where it could forge a ``TNR:`` line in the
    reshaped message.
    """
    return _WS_CHAR_REF.sub(" ", value or "")


def field_value(report: dict[str, str], aliases: Sequence[str]) -> str:
    """One value on one line, whichever of its aliases the plugin used as the key.

    A newline in operator text must not become a new ``Label:`` line, so the
    value is collapsed to single spaces.
    """
    for key, value in report.items():
        if normalize_key(key) in aliases:
            return " ".join(unescape_char_refs(value).split())
    return ""


def _from_epoch(raw: str) -> _dt.datetime | None:
    """``Skapad`` as local wall-clock time — 13 digits are ms, 10 are seconds."""
    if not raw.isdigit() or len(raw) not in (10, 13):
        return None
    seconds = int(raw) / 1000 if len(raw) == 13 else int(raw)
    try:
        moment = _dt.datetime.fromtimestamp(seconds, _dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    now = _dt.datetime.now(_dt.timezone.utc)
    if moment.year < _EPOCH_MIN_YEAR or moment > now + _EPOCH_MAX_AHEAD:
        return None
    return moment.astimezone(cfg.TIMEZONE).replace(tzinfo=None)


def parse_local(raw: str) -> _dt.datetime | None:
    """One time field as local wall-clock time, or None if it is not a time at all.

    The "8S" plugin writes local wall-clock text (``2026/09/14 22:02``), "HV
    Rapporter" writes ISO 8601 in UTC (``2026-06-12T15:29:17.000Z``), and
    ``Skapad`` is epoch milliseconds. Reading the second as if it were local
    would put the TNR two hours off in summer, so an explicit offset is honoured
    and converted rather than ignored.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:  # ISO 8601 first; it is the only form that can carry an offset.
        parsed = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M:%S"):
            try:
                return _dt.datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return _from_epoch(raw)
    return parsed.astimezone(cfg.TIMEZONE).replace(tzinfo=None) if parsed.tzinfo else parsed


def tnr_and_stund(parsed: _dt.datetime) -> tuple[str, str]:
    """``(TNR 'DDHHMM', Stund 'DDHHMMZMÅNÅÅÅÅ')`` for a resolved local time.

    The long ``Stund`` form is not decoration. ``resolve_report_datetime``
    resolves a bare ``DDHHMM`` against the *arrival* time and rolls back at most
    one month, so a report relayed late would land on the wrong month — in a real
    capture the relay delay was three months.
    """
    tnr = parsed.strftime("%d%H%M")
    return tnr, f"{tnr}Z{MONTHS_SV[parsed.month - 1]}{parsed.year}"


def stalle(cot: InboundCot, position: str) -> str:
    """``Ställe`` from the form's position text and the CoT point.

    ``seven_s._extract_location`` reads coordinates from a bare MGRS or from
    ``"<MGRS>, <place>"``, so the grid always comes first and in compact form.
    """
    compact = "".join(position.split()).upper()
    operator_point = _mgrs_to_latlon(compact) if position else None
    if operator_point is not None and distance_m(*operator_point, cot.lat, cot.lon) > SAME_CELL_M:
        return compact  # operator moved the position off the marker: their grid wins, CoT point stays in the raw block
    cot_mgrs = latlon_to_mgrs(cot.lat, cot.lon)
    if operator_point is not None or not position:
        return cot_mgrs or f"{cot.lat:.5f},{cot.lon:.5f}"  # a grid ref is not a place name: no "X, X"
    return f"{cot_mgrs}, {position}" if cot_mgrs else position  # prose place name (or no mgrs lib)


def raw_block(cot: InboundCot, label: str, *, extra: Iterable[str] = ()) -> str:
    """The trailing Obsidian ``%%`` comment carrying the form verbatim.

    Hidden in reading view, so nothing the operator typed is lost even where the
    reshaped report has no field for it. Only ``%%`` is neutered, so the comment
    cannot be closed early; everything else is left exactly as it arrived, which
    is what "oförändrad" promises.
    """

    def keep(value: str) -> str:
        return (value or "").replace("%%", "% %")

    raw = [f"{key}: {keep(value)}" for key, value in cot.custom_report.items()]
    if cot.remarks.strip():
        # to_7s_message used to drop remarks entirely; a SCRIM carries corrections there.
        raw.append(f"remarks: {keep(cot.remarks.strip())}")
    raw += [f"lat: {cot.lat}", f"lon: {cot.lon}", f"cot_uid: {cot.uid}", f"cot_typ: {cot.cot_type}"]
    raw += list(extra)
    return f"%%\n{label} (ATAK) rådata — oförändrad:\n" + "\n".join(raw) + "\n%%"
