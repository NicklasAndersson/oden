#!/usr/bin/env python3
"""Inspect an ATAK data package, and optionally connect with it.

Reads nothing from Oden's config-db and writes nothing to it, so it is safe to
run while Oden is running. Extracted certificates go to a temporary directory
that is deleted on exit.

    # what is in this package?
    python scripts/tak_check_package.py ~/.config/oden/tak/atak-box.zip

    # trust-only package: enroll for a cert and connect for real
    export ODEN_TAK_ENROLL_PASSWORD='...'
    python scripts/tak_check_package.py ~/.config/oden/tak/atak-box.zip --connect --user oden

    # send a marker once connected
    python scripts/tak_check_package.py pkg.zip --connect --user oden --send 34VCM7934926095
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from oden.tak.bridge import _DEFAULTS, TakBridge
from oden.tak.cot import Report, latlon_to_mgrs, report_to_cot
from oden.tak.pref_package import describe_package, read_data_package


def _describe(package, workdir: Path) -> None:
    print(f"Sort          : {package.kind}")
    print(f"Beskrivning   : {package.description or '—'}")
    print(f"Serveradress  : {package.cot_url}")
    print(f"Klientcert    : {package.client_cert or '— (paketet innehåller inget)'}")
    print(f"Server-CA     : {package.ca_pem or '— (paketet innehåller inget)'}")
    if package.ca_pem:
        from cryptography.x509 import load_pem_x509_certificates

        for cert in load_pem_x509_certificates(Path(package.ca_pem).read_bytes()):
            # not_valid_after_utc on cryptography >= 42, else the naive value.
            expiry = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
            print(f"  CA          : {cert.subject.rfc4514_string()}")
            print(f"    giltigt t.o.m. {expiry:%Y-%m-%d}")
    print()
    print(describe_package(package))
    print(f"\n(utpackat under {workdir}, tas bort när skriptet slutar)")


async def _connect(args: argparse.Namespace, package, workdir: Path) -> int:
    password = os.environ.get(args.password_env, "")
    if package.needs_enrollment and not (args.user and password):
        print(
            f"\nPaketet kräver enrollment. Kör igen med --user <namn> och {args.password_env} satt i miljön.",
            file=sys.stderr,
        )
        return 2

    settings = {
        **_DEFAULTS,
        "enabled": True,
        "pref_package": str(args.package),
        "enroll_username": args.user or "",
        "enroll_password_env": args.password_env,
        "callsign": args.callsign,
    }

    import oden.tak.bridge as bridge_mod

    bridge_mod.tak_dir = lambda: workdir  # keep key material out of ODEN_HOME

    bridge = TakBridge(settings)
    print(f"\nAnsluter till {package.cot_url} …")
    if package.needs_enrollment:
        print(f"(hämtar först ett klientcert från {args.user}@…:8446)")
    try:
        await bridge.start()
    except Exception as exc:
        print(f"\nMISSLYCKADES: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    try:
        print(f"ANSLUTEN (connected={bridge.connected})")
        if args.send:
            now = dt.datetime.now(dt.timezone.utc)
            import mgrs

            lat, lon = (float(v) for v in mgrs.MGRS().toLatLon(args.send.replace(" ", "")))
            tnr = now.strftime("%d%H%M")
            cot = report_to_cot(
                Report(
                    report_type="TEST",
                    tnr=tnr,
                    lat=lat,
                    lon=lon,
                    event_time=now,
                    start_time=now,
                    remarks=f"Oden testmarkör {latlon_to_mgrs(lat, lon) or args.send}",
                ),
                stale_seconds=bridge.stale_seconds,
                archive=bridge.archive,
                callsign=args.callsign,
            )
            print(f"Skickar ODEN.TEST.{tnr} ({lat:.5f}, {lon:.5f}) …")
            await bridge.publish(cot)
            await asyncio.sleep(3)  # let the TX worker drain before we close
            print("Skickad — leta efter markören i ATAK/CloudTAK.")
    finally:
        await bridge.stop()
    return 0


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path, help="sökväg till data-package-.zip")
    parser.add_argument("--connect", action="store_true", help="anslut på riktigt, inte bara läs paketet")
    parser.add_argument("--user", help="enrollment-användarnamn")
    parser.add_argument("--password-env", default="ODEN_TAK_ENROLL_PASSWORD", help="env-var med enrollment-lösenordet")
    parser.add_argument("--callsign", default="ODEN")
    parser.add_argument("--send", metavar="MGRS", help="skicka en testmarkör efter anslutning")
    args = parser.parse_args()

    with TemporaryDirectory(prefix="oden_tak_check_") as tmp:
        workdir = Path(tmp)
        try:
            package = read_data_package(str(args.package), workdir)
        except ValueError as exc:
            print(f"Kunde inte läsa paketet: {exc}", file=sys.stderr)
            return 1

        _describe(package, workdir)
        return await _connect(args, package, workdir) if args.connect else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
