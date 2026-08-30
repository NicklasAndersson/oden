"""TAK publish pipeline — pushes positioned reports to a TAK Server as CoT markers.

Non-consuming: it always returns ``False`` so the normal report pipelines still
run. It only does anything when the TAK bridge is up (``[TAK] enabled``).

Phase 2 handles 7S reports (the only report type that carries a position).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from oden.pipelines.seven_s import _extract_location, _mgrs_to_latlon, is_7s_message, parse_7s_report
from oden.pipelines.structured_report import extract_message_details
from oden.tak.bridge import get_tak_bridge
from oden.tak.cot import Report, report_to_cot

logger = logging.getLogger(__name__)


def _coords_from_stalle(stalle: str) -> tuple[float, float] | None:
    _plats, lat, lon = _extract_location(stalle)
    if lat is not None and lon is not None:
        return lat, lon
    return _mgrs_to_latlon(stalle.strip())


class TakPublishPipeline:
    name = "tak_publish"
    display_name = "TAK-publicering"
    description = "Skickar positionsförsedda rapporter till TAK Server som CoT-markörer. Konsumerar inte meddelandet."
    selection_criteria = (
        "Sidoeffekt: körs alltid först. Publicerar 7S-rapporter med koordinater när [TAK] är aktiverat."
    )

    async def run(self, *, msg_data: dict[str, Any], reader: Any, writer: Any) -> bool:
        del reader, writer
        self.last_warnings: list[dict[str, str]] = []

        bridge = get_tak_bridge()
        if bridge is None or not bridge.is_running:
            return False

        envelope = msg_data.get("envelope", {}) or {}
        if envelope.get("_source") == "tak":
            return False  # eko-skydd: skicka inte tillbaka det vi tog emot från TAK

        message_text, _group, _gid, ts_ms, _att, _quote = extract_message_details(envelope)
        if not is_7s_message(message_text):
            return False

        try:
            await self._publish_7s(bridge, message_text or "", ts_ms)
        except Exception as exc:
            logger.warning("tak_publish: kunde inte publicera 7S till TAK: %r", exc)
            self.last_warnings.append(
                {"field": "tak", "value": "", "message": f"TAK-publicering misslyckades: {exc!r}"}
            )
        return False

    async def _publish_7s(self, bridge: Any, message_text: str, ts_ms: int) -> None:
        fields = parse_7s_report(message_text)
        coords = _coords_from_stalle(fields["stalle"])
        if coords is None:
            self.last_warnings.append(
                {
                    "field": "stalle",
                    "value": fields["stalle"],
                    "message": "Ingen koordinat i Ställe — hoppar TAK-markör",
                }
            )
            return

        lat, lon = coords
        now = dt.datetime.now(dt.timezone.utc)
        # start = the report's own time, but never in the future (sender clock skew)
        start = min(dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc), now) if ts_ms else now

        cot = report_to_cot(
            Report(
                report_type="7S",
                tnr=fields["tnr"].strip(),
                lat=lat,
                lon=lon,
                event_time=now,
                start_time=start,
                remarks=message_text.strip(),
            ),
            stale_seconds=bridge.stale_seconds,
            archive=bridge.archive,
            callsign=str(bridge.settings.get("callsign") or ""),
        )
        published = await bridge.publish(cot)
        if published:
            logger.info("tak_publish: skickade 7S TNR %s till TAK", fields["tnr"].strip())
