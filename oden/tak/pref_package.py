"""ATAK data package (``.zip``) -> connection settings.

A data package is what a TAK admin hands out to onboard a client. Two kinds
exist, and they are not interchangeable:

``klientcert``   carries the client's own ``.p12`` (``certificateLocation`` +
                 ``clientPassword``). Everything needed to connect is inside.
``enrollment``   carries only the server's truststore (``caLocation0`` +
                 ``caPassword0``) plus ``enrollForCertificateWithTrust0``. The
                 client fetches its own cert from the server (port 8446) using a
                 username/password.

``pytak.read_pref_package`` only understands the first kind: it reads exactly
``connectString0``/``clientPassword``/``certificateLocation`` and derives the CA
from the client cert's own chain. Given an enrollment package it leaves
``certificate_location`` as ``None`` and then runs ``os.path.exists(None)``,
which raises an opaque ``TypeError`` from deep inside the library. pytak's
enrollment support is a separate feature that knows nothing about packages, so
nothing in pytak joins the two.

So we read the package ourselves, handle both kinds, convert the truststore to
the PEM that ``ssl.SSLContext.load_verify_locations`` needs, and report which
kind it was so the caller can say what is still missing.

See docs/TAK_SETUP.md.
"""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oden import config as cfg

logger = logging.getLogger(__name__)

# Key spellings seen in the wild. ATAK writes the unsuffixed client keys, while
# pytak's own package generator writes the "0"-suffixed ones; accept both.
_CONNECT_STRING_KEYS = ("connectString0", "connectString")
_DESCRIPTION_KEYS = ("description0", "description")
_CA_LOCATION_KEYS = ("caLocation0", "caLocation")
_CA_PASSWORD_KEYS = ("caPassword0", "caPassword")
_CLIENT_CERT_KEYS = ("certificateLocation", "certificateLocation0")
_CLIENT_PASSWORD_KEYS = ("clientPassword", "clientPassword0")
_ENROLL_KEYS = ("enrollForCertificateWithTrust0", "enrollForCertificateWithTrust", "useAuth0", "useAuth")

_PEM_SUFFIXES = (".pem", ".crt", ".cer")
_TRUE_VALUES = {"true", "1", "yes", "on"}


@dataclass(frozen=True)
class PackageConfig:
    """What one data package tells us about connecting."""

    cot_url: str
    description: str = ""
    client_cert: str = ""  # path to the extracted .p12, "" when the package has none
    client_password: str = ""
    ca_pem: str = ""  # path to the PEM bundle we wrote
    needs_enrollment: bool = False

    @property
    def kind(self) -> str:
        return "klientcert" if self.client_cert else ("enrollment" if self.needs_enrollment else "okänd")


def tak_dir() -> Path:
    """Where Oden keeps TAK key material: ``ODEN_HOME/tak``, created ``0700``."""
    return Path(cfg.ODEN_HOME) / "tak"


def _first(prefs: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = (prefs.get(key) or "").strip()
        if value:
            return value
    return ""


def _is_true(prefs: dict[str, str], keys: tuple[str, ...]) -> bool:
    return any((prefs.get(key) or "").strip().lower() in _TRUE_VALUES for key in keys)


def _connect_string_to_url(connect_string: str) -> str:
    """``"host:port:proto"`` -> ``"proto://host:port"``.

    pytak accepts ``ssl://`` as an alias for ``tls://``, which is what ATAK
    writes, so the protocol is passed through unchanged.
    """
    parts = connect_string.split(":")
    if len(parts) < 3 or not all(part.strip() for part in parts[:3]):
        raise ValueError(f"Oläslig connectString i data-paketet: {connect_string!r}")
    host, port, proto = (part.strip() for part in parts[:3])
    return f"{proto}://{host}:{port}"


def _parse_prefs(blob: bytes) -> dict[str, str]:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(blob)
    except ET.ParseError as exc:
        raise ValueError(f"Kunde inte tolka .pref-filen i data-paketet: {exc}") from exc
    prefs: dict[str, str] = {}
    for entry in root.findall(".//entry"):
        key = entry.attrib.get("key", "")
        if key and entry.text is not None:
            prefs.setdefault(key, entry.text)
    return prefs


def _find_member(zf: zipfile.ZipFile, location: str) -> str | None:
    """Resolve a ``.pref`` path like ``cert/caCert.p12`` to a real zip member.

    The path in the ``.pref`` is where ATAK puts the file, which is not always
    where it sits in the zip, so fall back to matching on the basename.
    """
    names = zf.namelist()
    if location in names:
        return location
    wanted = Path(location.replace("\\", "/")).name.lower()
    return next((name for name in names if Path(name).name.lower() == wanted), None)


def _write_secret(dest: Path, blob: bytes) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest.write_bytes(blob)
    dest.chmod(0o600)
    return str(dest)


def _truststore_to_pem(blob: bytes, password: str, dest: Path) -> str:
    """Convert a PKCS#12 truststore to a PEM bundle.

    A truststore holds CA certificates and no private key, so pytak's
    ``convert_cert``/``convert_p12_to_pem`` both crash on it — they go straight
    for ``private_key.private_bytes(...)``.
    """
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs12

    try:
        _key, cert, extra = pkcs12.load_key_and_certificates(blob, password.encode() or None)
    except Exception as exc:
        raise ValueError(
            f"Kunde inte låsa upp serverns CA ur data-paketet ({exc}). Stämmer caPassword i .pref-filen?"
        ) from exc

    certs = ([cert] if cert is not None else []) + list(extra or [])
    if not certs:
        raise ValueError("Serverns CA-fil i data-paketet innehåller inga certifikat")
    pem = b"".join(one.public_bytes(Encoding.PEM) for one in certs)
    logger.info("TAK: konverterade serverns CA ur data-paketet (%d certifikat)", len(certs))
    return _write_secret(dest, pem)


def read_data_package(zip_path: str, dest_dir: Path) -> PackageConfig:
    """Read an ATAK data package and extract what pytak needs to connect.

    Files pulled out of the package (client cert, CA bundle) are written to
    *dest_dir* as ``0600`` inside a ``0700`` directory — they are key material.
    Raises ``ValueError`` with a message meant for the operator.
    """
    path = Path(zip_path).expanduser()
    if not path.is_file():
        raise ValueError(f"Data-paketet finns inte: {path}")

    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Data-paketet är ingen giltig zip: {path}") from exc

    with zf:
        pref_name = next((name for name in zf.namelist() if name.lower().endswith(".pref")), None)
        if pref_name is None:
            raise ValueError("Data-paketet innehåller ingen .pref-fil — är det verkligen ett TAK-data-package?")
        prefs = _parse_prefs(zf.read(pref_name))

        connect_string = _first(prefs, _CONNECT_STRING_KEYS)
        if not connect_string:
            raise ValueError("Data-paketets .pref-fil saknar connectString — ingen serveradress att ansluta till")
        cot_url = _connect_string_to_url(connect_string)

        stem = path.stem

        ca_pem = ""
        ca_location = _first(prefs, _CA_LOCATION_KEYS)
        if ca_location:
            member = _find_member(zf, ca_location)
            if member is None:
                raise ValueError(f"Data-paketet pekar på CA-filen {ca_location!r} som inte finns i zip:en")
            blob = zf.read(member)
            if member.lower().endswith(_PEM_SUFFIXES):
                ca_pem = _write_secret(dest_dir / f"{stem}-ca.pem", blob)
            else:
                ca_pem = _truststore_to_pem(blob, _first(prefs, _CA_PASSWORD_KEYS), dest_dir / f"{stem}-ca.pem")

        client_cert = ""
        client_password = ""
        cert_location = _first(prefs, _CLIENT_CERT_KEYS)
        if cert_location:
            member = _find_member(zf, cert_location)
            if member is None:
                raise ValueError(f"Data-paketet pekar på klientcertet {cert_location!r} som inte finns i zip:en")
            suffix = Path(member).suffix or ".p12"
            client_cert = _write_secret(dest_dir / f"{stem}-client{suffix}", zf.read(member))
            client_password = _first(prefs, _CLIENT_PASSWORD_KEYS)

    return PackageConfig(
        cot_url=cot_url,
        description=_first(prefs, _DESCRIPTION_KEYS),
        client_cert=client_cert,
        client_password=client_password,
        ca_pem=ca_pem,
        needs_enrollment=not client_cert and _is_true(prefs, _ENROLL_KEYS),
    )


def describe_package(package: PackageConfig) -> str:
    """One line for the GUI: what this package is and what is still needed."""
    where = package.description or package.cot_url
    if package.client_cert:
        return f"Data package för {where} med klientcertifikat — klicka Spara för att ansluta."
    if package.needs_enrollment:
        return (
            f"Data package för {where} innehåller bara serverns CA. "
            "Fyll i enrollment-användarnamn och lösenord, klicka sedan Spara."
        )
    return f"Data package för {where} saknar både klientcertifikat och enrollment — fråga din TAK-admin."


def package_settings(settings: dict[str, Any], dest_dir: Path) -> PackageConfig | None:
    """Read the configured ``pref_package``, or None when none is configured."""
    pref_package = str(settings.get("pref_package") or "").strip()
    return read_data_package(pref_package, dest_dir) if pref_package else None
