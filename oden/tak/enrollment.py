"""Client-certificate enrollment against a TAK Server, owned by Oden.

pytak can enroll (``create_tls_client`` does, whenever
``PYTAK_TLS_CERT_ENROLLMENT_USERNAME``/``_PASSWORD`` are set) but it does so on
*every* connection: a fresh RSA-4096 key and a new CSR to the server each time
the bridge (re)connects, with the resulting ``.p12`` — private key included —
left behind in ``$TMPDIR`` (``NamedTemporaryFile(delete=False)``, never removed).
Its cert cache exists but is only reachable from the ``tak://`` deep-link flow.

So Oden enrolls once, keeps the ``.p12`` under ``ODEN_HOME/tak`` next to the
other TAK key material, reuses it while it is valid, and hands pytak a plain
client cert. pytak's enrollment branch never runs, and the operator's password
never enters pytak's configuration.

``begin_enrollment`` swallows its own exceptions and returns without writing a
cert, so a wrong password and a firewalled port 8446 look identical from
outside. The one place the reason survives is pytak's log, which is captured
for the duration of the call and put into the error the operator sees.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path

from oden.tak.pref_package import _write_secret
from oden.tak.redact import redact

logger = logging.getLogger(__name__)

# Renew while there is still time to notice a failing enrollment before the
# old cert stops working.
_RENEW_BEFORE = _dt.timedelta(days=7)
_PYTAK_ENROLL_LOGGER = "pytak.crypto_classes"
ENROLLMENT_PORT = 8446  # hardcoded inside pytak's CertificateEnrollment


@dataclass(frozen=True)
class EnrolledCert:
    path: str  # .p12 under ODEN_HOME/tak
    passphrase: str  # ours: token_urlsafe, so never a "%" for a ConfigParser to trip on
    expires_at: _dt.datetime


def _cache_paths(host: str, username: str, dest_dir: Path) -> tuple[Path, Path]:
    """``(p12, passphrase)`` for this server+account — a new server or account gets its own cert."""
    key = hashlib.sha256(f"{host}:{username}".encode()).hexdigest()[:32]
    return dest_dir / f"enrolled-{key}.p12", dest_dir / f"enrolled-{key}.pass"


def _expiry(p12: bytes, passphrase: str) -> _dt.datetime:
    from cryptography.hazmat.primitives.serialization import pkcs12

    _key, cert, _extra = pkcs12.load_key_and_certificates(p12, passphrase.encode())
    if cert is None:
        raise ValueError("inget klientcertifikat i .p12-filen")
    # not_valid_after_utc (aware) on cryptography >= 42, else the naive value.
    expiry = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
    return expiry if expiry.tzinfo else expiry.replace(tzinfo=_dt.timezone.utc)


def cached_cert(host: str, username: str, dest_dir: Path, *, now: _dt.datetime | None = None) -> EnrolledCert | None:
    """The cached cert for this server+account if it is still good for a while, else None."""
    p12_path, pass_path = _cache_paths(host, username, dest_dir)
    if not (p12_path.is_file() and pass_path.is_file()):
        return None
    passphrase = pass_path.read_text().strip()
    try:
        expires_at = _expiry(p12_path.read_bytes(), passphrase)
    except Exception as exc:
        logger.warning("TAK: cachat enrollment-cert %s går inte att läsa (%s) — hämtar ett nytt", p12_path.name, exc)
        return None
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if expires_at - now < _RENEW_BEFORE:
        logger.info("TAK: enrollment-certet går ut %s — förnyar", expires_at.date())
        return None
    return EnrolledCert(str(p12_path), passphrase, expires_at)


class _CaptureWarnings(logging.Handler):
    """Collect pytak's WARNING+ lines while enrollment runs; they are the only error report we get."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


async def enroll(host: str, username: str, password: str, dest_dir: Path) -> EnrolledCert:
    """Fetch a client cert from ``host``:8446 and cache it. Raises ValueError with the reason on failure."""
    from pytak.crypto_classes import CertificateEnrollment

    p12_path, pass_path = _cache_paths(host, username, dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A stale pair must not be mistaken for the result of this attempt.
    p12_path.unlink(missing_ok=True)
    pass_path.unlink(missing_ok=True)
    passphrase = secrets.token_urlsafe(16)

    logger.info("TAK: hämtar klientcert från %s:%d som %s", host, ENROLLMENT_PORT, username)
    capture = _CaptureWarnings()
    pytak_log = logging.getLogger(_PYTAK_ENROLL_LOGGER)
    pytak_log.addHandler(capture)
    try:
        await CertificateEnrollment().begin_enrollment(
            domain=host,
            username=username,
            password=password,
            output_path=str(p12_path),
            passphrase=passphrase,
        )
    except Exception as exc:  # pytak normally swallows these; belt and braces
        capture.lines.append(repr(exc))
    finally:
        pytak_log.removeHandler(capture)

    if not p12_path.is_file() or p12_path.stat().st_size == 0:
        p12_path.unlink(missing_ok=True)
        reason = redact("; ".join(capture.lines) or "servern skickade inget certifikat", password)
        raise ValueError(
            f"TAK: enrollment mot {host}:{ENROLLMENT_PORT} som {username} misslyckades — {reason}. "
            "Kontrollera användarnamn och lösenord, och att porten är nåbar."
        )

    p12_path.chmod(0o600)
    try:
        expires_at = _expiry(p12_path.read_bytes(), passphrase)
    except Exception as exc:
        p12_path.unlink(missing_ok=True)
        raise ValueError(f"TAK: servern svarade på enrollment men certet gick inte att läsa: {exc}") from exc
    _write_secret(pass_path, passphrase.encode())

    logger.info("TAK: enrollment klar — certet är giltigt t.o.m. %s och cachat i %s", expires_at.date(), p12_path)
    return EnrolledCert(str(p12_path), passphrase, expires_at)


async def ensure_cert(host: str, username: str, password: str, dest_dir: Path) -> EnrolledCert:
    """A valid client cert for this server+account: from the cache when possible, else freshly enrolled."""
    cached = cached_cert(host, username, dest_dir)
    if cached is not None:
        logger.info("TAK: återanvänder cachat enrollment-cert (giltigt t.o.m. %s)", cached.expires_at.date())
        return cached
    return await enroll(host, username, password, dest_dir)
