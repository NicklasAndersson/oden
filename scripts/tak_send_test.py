#!/usr/bin/env python3
"""Send one test CoT marker to a TAK Server, without going through Signal.

Reads TAK config from Oden's config-db (the ``tak_settings`` key). Use it to
verify connectivity/certs before wiring up a real 7S flow.

    python scripts/tak_send_test.py 34VCM7934926095
    python scripts/tak_send_test.py --lat 59.33 --lon 18.07 --affiliation hostile
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt

from oden.tak.bridge import TakBridge, load_tak_settings
from oden.tak.cot import Report, latlon_to_mgrs, report_to_cot


def _latlon(args: argparse.Namespace) -> tuple[float, float]:
    if args.mgrs:
        import mgrs

        lat, lon = mgrs.MGRS().toLatLon(args.mgrs.replace(" ", ""))
        return float(lat), float(lon)
    if args.lat is None or args.lon is None:
        raise SystemExit("Ange antingen MGRS-position eller --lat och --lon")
    return args.lat, args.lon


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mgrs", nargs="?", help="MGRS-position, t.ex. 34VCM7934926095")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--tnr", default=dt.datetime.now().strftime("%d%H%M"))
    parser.add_argument("--affiliation", default="unknown", choices=["unknown", "friendly", "hostile", "neutral"])
    args = parser.parse_args()

    lat, lon = _latlon(args)
    settings = load_tak_settings()
    if not settings.get("enabled"):
        raise SystemExit("tak_settings.enabled är false — aktivera TAK först")

    bridge = TakBridge(settings)
    await bridge.start()
    try:
        cot = report_to_cot(
            Report(
                report_type="TEST",
                tnr=args.tnr,
                lat=lat,
                lon=lon,
                event_time=dt.datetime.now(dt.timezone.utc),
                start_time=dt.datetime.now(dt.timezone.utc),
                remarks=f"Oden testmarkör {latlon_to_mgrs(lat, lon)}",
                affiliation=args.affiliation,
            ),
            stale_seconds=bridge.stale_seconds,
            archive=bridge.archive,
            callsign=str(settings.get("callsign") or ""),
        )
        ok = await bridge.publish(cot)
        print(f"publicerad: {ok}  ({lat:.5f}, {lon:.5f})  uid=ODEN.TEST.{args.tnr}")
        await asyncio.sleep(3)  # ge TX-worker tid att skicka innan vi stänger
    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(_main())
