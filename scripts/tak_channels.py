"""Fråga TAK-servern vilka kanaler Odens konto tillhör, och vem mer som är ansluten.

Oden vet inte själv. Kanaltillhörighet (TAK Servers "channels", internt groups)
sitter på servern, knuten till certifikatet — den skickas aldrig till klienten som
en lista, och Oden läser inte ens ``__group`` i inkommande CoT. Får man inga noter
fast allt annat ser rätt ut är det därför svårt att utesluta kanalerna. Det här
skriptet frågar serverns Marti-API med Odens eget klientcert, alltså exakt det
konto bryggan använder.

Rör inte config.db, valvet eller Signal, och skriver ingenting bestående — går
att köra medan Oden är igång.

    .venv/bin/python scripts/tak_channels.py ~/.config/oden/tak/paket.zip --user 25HVBAT675

Certet måste redan vara hämtat, alltså efter en lyckad anslutning eller efter
tak_check_package.py --connect. API:t ligger normalt på 8443 (--port för annat).
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: E402

from oden.tak.enrollment import cached_cert  # noqa: E402
from oden.tak.pref_package import read_data_package, tak_dir  # noqa: E402

# Marti-API:t. groups/all är svaret på frågan; de andra två är sammanhang: vilka
# klienter servern ser på det här kontot, och vilken serverversion det är.
_ENDPOINTS = (
    ("kanaler", "/Marti/api/groups/all"),
    ("anslutna klienter", "/Marti/api/clientEndPoints"),
    ("serverversion", "/Marti/api/version"),
)


def _client_pem(p12_path: Path, passphrase: str, dest: Path) -> Path:
    """Odens cachade .p12 som PEM, eftersom ssl-modulen inte läser PKCS#12."""
    key, cert, _chain = pkcs12.load_key_and_certificates(p12_path.read_bytes(), passphrase.encode())
    if key is None or cert is None:
        raise ValueError(f"{p12_path.name} innehåller inte både nyckel och certifikat")
    pem = dest / "client.pem"
    pem.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        + cert.public_bytes(serialization.Encoding.PEM)
    )
    pem.chmod(0o600)
    return pem


def _get(url: str, ctx: ssl.SSLContext, timeout: float) -> tuple[int, str]:
    """(status, body). urllib sköter chunked svar och statuskoder; vi bara bär certet."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # 401/403/404 är svar, inte haverier
        return exc.code, exc.read().decode("utf-8", "replace")


def _print_channels(payload: object) -> None:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        print("  Servern svarade utan kanallista — kontot kan sakna kanaler.")
        return
    print(f"  {'kanal':28s}{'riktning':10s}{'aktiv':7s}typ")
    for row in rows:
        if not isinstance(row, dict):
            print(f"  {row}")
            continue
        name = str(row.get("name", "?"))
        direction = str(row.get("direction", "?"))
        active = "ja" if row.get("active") else "nej"
        print(f"  {name:28s}{direction:10s}{active:7s}{row.get('type', '')}")
    print("\n  Oden ser bara trafik i kanaler där riktningen omfattar IN och som är aktiva.")
    print("  Skickar din ATAK-enhet i en kanal som inte står här kommer ingenting fram.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path, help="data-paketet Oden ansluter med (för serverns CA)")
    parser.add_argument("--user", required=True, help="enrollment-användarnamnet Oden använder")
    parser.add_argument("--port", type=int, default=8443, help="Marti-API-port (default 8443)")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--check-hostname", action="store_true", help="kräv att certet matchar adressen")
    args = parser.parse_args()

    with TemporaryDirectory(prefix="oden_tak_channels_") as tmp:
        workdir = Path(tmp)
        try:
            package = read_data_package(str(args.package), workdir)
        except ValueError as exc:
            print(f"Kunde inte läsa paketet: {exc}", file=sys.stderr)
            return 1

        host = package.cot_url.split("://", 1)[-1].rsplit(":", 1)[0]
        cert = cached_cert(host, args.user, tak_dir())
        if cert is None:
            print(
                f"Inget cachat klientcert för {args.user}@{host} i {tak_dir()}.\n"
                "Anslut först, t.ex. med scripts/tak_check_package.py --connect, så hämtas ett.",
                file=sys.stderr,
            )
            return 2

        ctx = ssl.create_default_context(cafile=package.ca_pem or None)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        # Odens dokumenterade default: TAK-cert matchar sällan adressen man ringer.
        # CA-verifieringen är kvar — det är bara namnkontrollen som stängs av.
        ctx.check_hostname = args.check_hostname
        if not package.ca_pem:
            print("Paketet har ingen CA — kan inte verifiera servern.", file=sys.stderr)
            return 1
        ctx.load_cert_chain(_client_pem(Path(cert.path), cert.passphrase, workdir))

        print(f"Frågar {host}:{args.port} som {args.user} (cert giltigt t.o.m. {cert.expires_at:%Y-%m-%d})\n")
        failures = 0
        for label, path in _ENDPOINTS:
            print(f"{label} — {path}")
            try:
                status, body = _get(f"https://{host}:{args.port}{path}", ctx, args.timeout)
            except (OSError, ssl.SSLError) as exc:
                print(f"  gick inte att nå: {exc}\n")
                failures += 1
                continue
            if status != 200:
                hint = {
                    401: "certet duger inte för API:t — be TAK-admin ge kontot webbläsbehörighet",
                    403: "kontot får inte läsa det här — be TAK-admin om behörighet",
                    404: "den här servern exponerar inte endpointen",
                }.get(status, "")
                print(f"  HTTP {status}{' — ' + hint if hint else ''}\n")
                failures += 1
                continue
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                print(f"  svarade inte JSON: {body[:200]}\n")
                failures += 1
                continue
            if path.endswith("groups/all"):
                _print_channels(payload)
            else:
                print("  " + json.dumps(payload, ensure_ascii=False)[:600])
            print()

        if failures == len(_ENDPOINTS):
            print(
                "Ingen fråga gick igenom. Är porten rätt? Marti-API:t ligger normalt på 8443,\n"
                "medan CoT-strömmen går på 8089 och enrollment på 8446. Annars är det\n"
                "TAK-admin som får läsa upp kanalerna för kontot ur adminvyn.",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
