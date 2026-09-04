"""CoT (Cursor on Target) XML <-> Oden report mapping.

Pure functions, stdlib only (plus the ``mgrs`` lib already used elsewhere for the
one reverse-geocode helper). No network here — the bridge/listener use this.

Outbound:  ``report_to_cot`` turns a normalized report dict into a CoT ``<event>``.
Inbound:   ``cot_to_inbound`` parses a received ``<event>`` into ``InboundCot``.

Design notes (see docs/PLAN_TAK.md):
- UID is stable and derived from report type + TNR, so an updated/appended report
  replaces its marker instead of duplicating it.
- ``how="h-g-i-g-o"`` — human, entered manually (not machine/GPS).
- Affiliation defaults to "unknown"; only narrow it when the caller is sure.
- Inbound text (callsign/uid/remarks) is untrusted: sanitize before it touches
  filenames, clamp coordinates, truncate remarks.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

UID_PREFIX = "ODEN"
_UNKNOWN_VAL = "9999999.0"  # CoT sentinel for unknown hae/ce/le
_COT_TIME_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
_MAX_REMARKS = 4096
_MAX_CUSTOM_FIELDS = 64  # e.g. ATAK Reports-plugin <custom_report> blocks (8-line etc.)
_MAX_CUSTOM_FIELD_LEN = 512

# Affiliation -> CoT 2525 atom type (ground). Air/sea not needed for reports.
AFFIL_TO_TYPE = {
    "friendly": "a-f-G",
    "hostile": "a-h-G",
    "neutral": "a-n-G",
    "unknown": "a-u-G",
}
_TYPE_TO_AFFIL = {v[:4]: k for k, v in AFFIL_TO_TYPE.items()}  # "a-f-" -> "friendly"

_TOKEN_OK = re.compile(r"[^A-Za-z0-9 ._-]+")


def sanitize_token(value: str, *, max_len: int = 64) -> str:
    """Make a callsign/uid safe for filenames and logs. Never returns ``..``."""
    cleaned = _TOKEN_OK.sub("_", (value or "").strip())
    cleaned = cleaned.replace("..", "_").strip(" ._-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:max_len] or "okänd"


def make_uid(report_type: str, tnr: str) -> str:
    return f"{UID_PREFIX}.{sanitize_token(report_type, max_len=16)}.{sanitize_token(tnr, max_len=32)}".replace(" ", "")


def _fmt_time(value: _dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(_dt.timezone.utc).strftime(_COT_TIME_FMT)[:-4] + "Z"


def _parse_time(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def _valid_latlon(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and not (lat == 0.0 and lon == 0.0)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine. Good enough for "has it moved?" / "same grid cell?" tests."""
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Report:
    """Normalized input for :func:`report_to_cot`. Pipelines adapt to this."""

    report_type: str  # "7S", "FORS", "PEDARS"
    tnr: str
    lat: float
    lon: float
    event_time: _dt.datetime  # when Oden received/processed it
    start_time: _dt.datetime  # the report's own timestamp (Stund)
    remarks: str  # full human-readable report text
    affiliation: str = "unknown"  # key of AFFIL_TO_TYPE
    hae: float | None = None


def report_to_cot(
    report: Report,
    *,
    stale_seconds: int = 3600,
    archive: bool = True,
    callsign: str = "",
) -> bytes:
    """Build a CoT ``<event>`` for a positioned report. Returns UTF-8 XML bytes.

    ``callsign`` (the ``[TAK]`` identity) is prefixed onto the marker's contact
    callsign so operators can tell which Oden instance a marker came from.
    """
    if not _valid_latlon(report.lat, report.lon):
        raise ValueError(f"report_to_cot: invalid lat/lon {report.lat},{report.lon}")

    cot_type = AFFIL_TO_TYPE.get(report.affiliation, AFFIL_TO_TYPE["unknown"])
    uid = make_uid(report.report_type, report.tnr)
    stale = report.event_time + _dt.timedelta(seconds=max(1, stale_seconds))

    event = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": uid,
            "type": cot_type,
            "how": "h-g-i-g-o",
            "time": _fmt_time(report.event_time),
            "start": _fmt_time(report.start_time),
            "stale": _fmt_time(stale),
        },
    )
    ET.SubElement(
        event,
        "point",
        {
            "lat": f"{report.lat:.7f}",
            "lon": f"{report.lon:.7f}",
            "hae": f"{report.hae:.1f}" if report.hae is not None else _UNKNOWN_VAL,
            "ce": _UNKNOWN_VAL,
            "le": _UNKNOWN_VAL,
        },
    )
    detail = ET.SubElement(event, "detail")
    marker_callsign = f"{callsign} {report.report_type} {report.tnr}".strip()
    ET.SubElement(detail, "contact", {"callsign": marker_callsign})
    remarks = ET.SubElement(detail, "remarks")
    remarks.text = (report.remarks or "")[:_MAX_REMARKS]
    ET.SubElement(detail, "link", {"uid": uid, "type": cot_type, "relation": "p-p"})
    if archive:
        ET.SubElement(detail, "archive")

    return ET.tostring(event, encoding="utf-8", xml_declaration=False)


@dataclass(frozen=True)
class InboundCot:
    uid: str
    cot_type: str
    how: str
    lat: float
    lon: float
    hae: float | None
    callsign: str
    remarks: str
    event_time: _dt.datetime
    stale: _dt.datetime | None
    is_chat: bool
    custom_report_name: str = ""
    custom_report: dict[str, str] = field(default_factory=dict)
    # The device that produced the event (<creator uid>/<link relation="p-p" uid>),
    # stable across everything one operator places — unlike the per-marker uid.
    operator_uid: str = ""
    operator_callsign: str = ""

    @property
    def affiliation(self) -> str:
        return _TYPE_TO_AFFIL.get(self.cot_type[:4], "unknown")

    @property
    def sender_id(self) -> str:
        """Best stable identity for "who sent this": the operator's device, else the marker."""
        return self.operator_uid or self.uid


# Standard CoT/ATAK <detail> children that every client attaches (device status,
# group membership, rendering hints, ...). Never treat these as report fields.
_KNOWN_DETAIL_TAGS = {
    "contact",
    "remarks",
    "link",
    "archive",
    "precisionlocation",
    "status",
    "uid",
    "takv",
    "track",
    "color",
    "usericon",
    "height",
    "marti",
    "attachment_list",
    "video",
    "chatgrp",
    "geofence",
    "environment",
    "emergency",
    "bloodhound",
    "routeinfo",
    "shape",
    "fillColor",
    "strokeColor",
    "labels_on",
    "creator",
    "hideLabel",
    "_flow-tags_",
    "_medevac_status_",
    "modelInfo",
}
_MAX_FIELD_DEPTH = 6
# Attribute names that are structure/plumbing, never a report field value.
_STRUCTURAL_ATTRS = {
    "value",
    "name",
    "label",
    "uid",
    "type",
    "relation",
    "time",
    "how",
    "version",
    "parent_callsign",
    "production_time",
    "geopointsrc",
    "altsrc",
}
_ATTR_NAME_JUNK = re.compile(r"[0-9a-f]{8}|^TAK-Server-|^_")


def _humanize_tag(tag: str) -> str:
    return tag.replace("_", " ").replace("-", " ").strip().title() or tag


def _extract_report_fields(elem: ET.Element, fields: dict[str, str], *, depth: int = 0) -> None:
    """Walk one report block and collect its fields, whatever shape it turns out to be.

    Handles both conventions seen across ATAK report-form templates: a value in the
    element's text (``<line1_size>3x Personnel</line1_size>``), or in a ``value``
    attribute keyed by ``name``/``label`` (``<field name="Size" value="..."/>``).
    """
    if depth > _MAX_FIELD_DEPTH or len(fields) >= _MAX_CUSTOM_FIELDS:
        return
    attr_value = (elem.get("value") or "").strip()
    if attr_value:
        key = elem.get("label") or elem.get("name") or elem.tag
        fields.setdefault(key, attr_value[:_MAX_CUSTOM_FIELD_LEN])

    # Many templates (e.g. the 8S form) flatten every field into attributes on
    # one wrapper element: <_8S_ POSITION="..." STRENGTH_TYPE="..." .../>
    for attr_name, attr_val in elem.attrib.items():
        if len(fields) >= _MAX_CUSTOM_FIELDS:
            break
        val = (attr_val or "").strip()
        if not val or attr_name in _STRUCTURAL_ATTRS or _ATTR_NAME_JUNK.search(attr_name):
            continue
        fields.setdefault(_humanize_tag(attr_name), val[:_MAX_CUSTOM_FIELD_LEN])

    children = list(elem)
    if not children:
        text = (elem.text or "").strip()
        if text and not attr_value:
            fields.setdefault(elem.tag, text[:_MAX_CUSTOM_FIELD_LEN])
        return
    for child in children:
        if len(fields) >= _MAX_CUSTOM_FIELDS:
            break
        _extract_report_fields(child, fields, depth=depth + 1)


def _parse_custom_report(detail: ET.Element) -> tuple[str, dict[str, str]]:
    """Pull operator-defined report fields out of ``<detail>``.

    ATAK report forms are built from a custom XML template and shipped as a Data
    Package, so there is no one fixed schema: the wrapper tag name, the field tag
    names, and whether a value lives in element text or an attribute all vary by
    template. So instead of matching one exact shape, treat any ``<detail>`` child
    that isn't a standard CoT element as a report block and walk it generically.
    Untrusted input: cap depth, field count and length; skip empty values.
    """
    name = ""
    fields: dict[str, str] = {}
    for child in detail:
        if child.tag.startswith("__") or child.tag in _KNOWN_DETAIL_TAGS:
            continue
        if not name:
            name = sanitize_token(child.get("name", "") or _humanize_tag(child.tag), max_len=64)
        _extract_report_fields(child, fields)
        if len(fields) >= _MAX_CUSTOM_FIELDS:
            break
    return name, fields


def cot_to_inbound(xml: bytes | str) -> InboundCot | None:
    """Parse a received CoT ``<event>``.

    Returns ``None`` for anything without a usable position (pings, malformed,
    (0,0), out-of-range). Text fields are sanitized/truncated here.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        logger.debug("cot_to_inbound: parse error: %s", exc)
        return None
    if root.tag != "event":
        return None

    point = root.find("point")
    if point is None:
        return None
    try:
        lat = float(point.get("lat", ""))
        lon = float(point.get("lon", ""))
    except ValueError:
        return None
    if not _valid_latlon(lat, lon):
        return None

    try:
        hae_raw = float(point.get("hae", _UNKNOWN_VAL))
        hae = None if hae_raw >= 9_999_999.0 else hae_raw
    except ValueError:
        hae = None

    detail = root.find("detail")
    callsign = ""
    remarks = ""
    is_chat = False
    custom_report_name = ""
    custom_report: dict[str, str] = {}
    operator_uid = ""
    operator_callsign = ""
    if detail is not None:
        contact = detail.find("contact")
        if contact is not None:
            callsign = contact.get("callsign", "")
        remarks_el = detail.find("remarks")
        if remarks_el is not None and remarks_el.text:
            remarks = remarks_el.text
        is_chat = detail.find("__chat") is not None or root.get("type", "").startswith("b-t-f")
        custom_report_name, custom_report = _parse_custom_report(detail)
        creator = detail.find("creator")
        parent = next((el for el in detail.findall("link") if el.get("relation") == "p-p"), None)
        raw_uid = (creator.get("uid", "") if creator is not None else "") or (
            parent.get("uid", "") if parent is not None else ""
        )
        raw_callsign = parent.get("parent_callsign", "") if parent is not None else ""
        operator_uid = sanitize_token(raw_uid, max_len=128) if raw_uid.strip() else ""
        operator_callsign = sanitize_token(raw_callsign, max_len=64) if raw_callsign.strip() else ""

    event_time = _parse_time(root.get("time")) or _dt.datetime.now(_dt.timezone.utc)

    return InboundCot(
        uid=sanitize_token(root.get("uid", ""), max_len=128),
        cot_type=root.get("type", ""),
        how=root.get("how", ""),
        lat=lat,
        lon=lon,
        hae=hae,
        callsign=sanitize_token(callsign or root.get("uid", ""), max_len=64),
        remarks=remarks[:_MAX_REMARKS],
        event_time=event_time,
        stale=_parse_time(root.get("stale")),
        is_chat=is_chat,
        custom_report_name=custom_report_name,
        custom_report=custom_report,
        operator_uid=operator_uid,
        operator_callsign=operator_callsign,
    )


def cot_type_matches(cot_type: str, patterns: list[str]) -> bool:
    """Match a CoT type against patterns like ``a-h-*`` (prefix) or exact ``a-h-G``."""
    for pattern in patterns:
        pattern = pattern.strip()
        if not pattern:
            continue
        if pattern.endswith("*"):
            if cot_type.startswith(pattern[:-1]):
                return True
        elif cot_type == pattern:
            return True
    return False


def latlon_to_mgrs(lat: float, lon: float) -> str:
    """Best-effort lat/lon -> MGRS for display. Empty string if mgrs is missing."""
    try:
        import mgrs

        return str(mgrs.MGRS().toMGRS(lat, lon))
    except Exception as exc:  # pragma: no cover - depends on optional native lib
        logger.debug("latlon_to_mgrs failed: %s", exc)
        return ""
