#!/usr/bin/env python3
"""Inspect an ATAK data package, and optionally connect with it.

Reads nothing from Oden's config-db and writes nothing to it, so it is safe to
run while Oden is running. The read-only inspection unpacks into a temporary
directory that is deleted on exit; ``--connect`` uses ``ODEN_HOME/tak`` exactly
like a normal Oden run, so the enrolled client cert is cached there and the
*second* run should connect without touching port 8446 at all.

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

from oden.tak.bridge import _DEFAULTS, TakBridge, safe_error
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
    password = os.environ.get(args.env_var, "")
    if package.needs_enrollment and not (args.user and password):
        print(
            f"\nPaketet kräver enrollment. Kör igen med --user <namn> och {args.env_var} satt i miljön.",
            file=sys.stderr,
        )
        return 2

    settings = {
        **_DEFAULTS,
        "enabled": True,
        "pref_package": str(args.package),
        "enroll_username": args.user or "",
        "enroll_password_env": args.env_var,
        "callsign": args.callsign,
    }

    from oden.tak.enrollment import cached_cert
    from oden.tak.pref_package import tak_dir

    bridge = TakBridge(settings)
    print(f"\nAnsluter till {package.cot_url} …")
    if package.needs_enrollment:
        host = package.cot_url.split("://", 1)[-1].rsplit(":", 1)[0]
        cached = cached_cert(host, args.user, tak_dir())
        if cached:
            print(f"(återanvänder cachat klientcert, giltigt t.o.m. {cached.expires_at:%Y-%m-%d} — ingen enrollment)")
        else:
            print(f"(hämtar först ett klientcert från {args.user}@{host}:8446, cachas i {tak_dir()})")
    try:
        await bridge.start()
    except Exception as exc:
        print(f"\nMISSLYCKADES: {safe_error(exc, settings)}", file=sys.stderr)
        return 1

    try:
        print(f"ANSLUTEN (connected={bridge.connected})")
        if bridge.enrolled:
            print(f"Klientcert: {bridge.enrolled.path} (giltigt t.o.m. {bridge.enrolled.expires_at:%Y-%m-%d})")
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
    # dest=env_var, inte password_env: hjälptexten skriver ut env-varens NAMN, och ett
    # attribut som heter *password* läses av CodeQL som själva hemligheten (falskt larm).
    parser.add_argument(
        "--password-env",
        dest="env_var",
        default="ODEN_TAK_ENROLL_PASSWORD",
        help="env-var med enrollment-lösenordet",
    )
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
