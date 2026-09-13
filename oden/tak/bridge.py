"""pytak-backed connection to a TAK Server.

Outbound: pipelines call ``publish`` with a CoT event. Inbound: ``listener``
drains ``rx_queue``. The tx/rx queues belong to the bridge, not to the pytak
``CLITool``, so a reconnect swaps the connection without losing queued markers
or the listener waiting on the queue.

``pytak`` is an optional dependency (``oden[tak]``); it is imported lazily inside
``TakBridge`` so nothing here is required unless TAK is enabled.

See docs/PLAN_TAK.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from configparser import ConfigParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from oden import config as cfg
from oden.config_db import get_config_value
from oden.tak.enrollment import EnrolledCert, ensure_cert
from oden.tak.pref_package import package_settings, tak_dir
from oden.tak.redact import redact

logger = logging.getLogger(__name__)

# asyncio.open_connection has no timeout of its own — a blackholed host would
# otherwise hang "Spara" in the GUI forever.
_CONNECT_TIMEOUT = 20.0
# ponytail: plain exponential backoff, no jitter — one Oden per server.
_RECONNECT_MIN = 5.0
_RECONNECT_MAX = 300.0

_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "cot_url": "",
    "pref_package": "",
    "tls_client_cert": "",
    "tls_client_key": "",
    "tls_client_password_env": "ODEN_TAK_CERT_PASSWORD",
    "tls_client_password": "",
    "tls_ca_cert": "",
    "tls_verify": True,
    # Many TAK Servers present a cert whose CN/SAN is not the DNS name you dial.
    # Turning this off keeps CA verification but skips the hostname check.
    "tls_check_hostname": False,
    # Certificate enrollment (username/password against the server, port 8446).
    # The password comes from the env var named here when that variable is set,
    # otherwise from enroll_password (typed in the TAK tab).
    "enroll_username": "",
    "enroll_password_env": "ODEN_TAK_ENROLL_PASSWORD",
    "enroll_password": "",
    "callsign": "ODEN",
    "cot_stale_seconds": 3600,
    "cot_archive": True,
    # inbound defaults live in oden.tak.listener._INBOUND_DEFAULTS
}


def load_tak_settings() -> dict[str, Any]:
    raw = get_config_value(cfg.CONFIG_DB, "tak_settings") or {}
    return {**_DEFAULTS, **raw}


def _secret(settings: dict[str, Any], env_key: str, value_key: str) -> str:
    """Resolve a password: the environment variable when it is actually set, else the stored value.

    ``env_key`` names the *setting* holding the environment variable's name, so
    an operator can keep the secret out of the config db. Falling back only when
    the variable is genuinely absent matters: both ``*_password_env`` settings
    have a default, so keying off "is a variable name configured" would make the
    stored value unreachable.
    """
    env_name = str(settings.get(env_key) or "").strip()
    from_env = os.environ.get(env_name, "") if env_name else ""
    return from_env or str(settings.get(value_key) or "")


# (setting holding the env var name, setting holding the literal value)
_SECRET_SETTINGS = (
    ("tls_client_password_env", "tls_client_password"),
    ("enroll_password_env", "enroll_password"),
)


# pytak's get_tls_config() copies these keys into a ConfigParser of its own, and
# that one does interpolate — so a literal "%" has to reach it doubled. Keys it
# does not touch (COT_URL) are read straight off our section and stay as-is.
# tests/test_tak_bridge.py pins this against the real pytak, so a pytak that
# stops interpolating fails the suite instead of silently sending "%%".
_PYTAK_REPARSED_PREFIX = "PYTAK_TLS_"


def _escape_for_pytak(key: str, value: str) -> str:
    return value.replace("%", "%%") if key.startswith(_PYTAK_REPARSED_PREFIX) else value


def safe_error(exc: BaseException, settings: dict[str, Any]) -> str:
    """``repr(exc)`` with any configured password scrubbed out.

    Errors from this module end up in the log, in ``last_error`` and on the TAK
    tab's status row, and library exceptions quote the value that upset them —
    ConfigParser puts a rejected password straight into its message. Matching on
    the actual secret works whatever shape the message takes.
    """
    return redact(repr(exc), *(_secret(settings, env_key, value_key) for env_key, value_key in _SECRET_SETTINGS))


def cert_expiry(settings: dict[str, Any]) -> datetime | None:
    """Best-effort expiry date of the configured client cert.

    Needs ``cryptography`` (ships with ``pytak[with-crypto]``). Returns None when
    it is unavailable, no cert is configured, or the file cannot be read — this
    is a GUI convenience, never a gate on connecting.
    """
    path = str(settings.get("tls_client_cert") or "").strip()
    if not path:
        return None
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography.x509 import load_pem_x509_certificate

        blob = Path(os.path.expanduser(path)).read_bytes()
        if path.lower().endswith((".p12", ".pfx")):
            password = _secret(settings, "tls_client_password_env", "tls_client_password")
            _key, cert, _chain = pkcs12.load_key_and_certificates(blob, password.encode() or None)
        else:
            cert = load_pem_x509_certificate(blob)
        if cert is None:
            return None
        # not_valid_after_utc (aware) on cryptography >= 42, else the naive value.
        expiry = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
        return expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)
    except Exception as exc:
        logger.debug("Kunde inte läsa certifikatets utgångsdatum: %s", exc)
        return None


class TakBridge:
    """Owns one pytak ``CLITool`` and its tx/rx queues."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self._config: Any = None
        self._clitool: Any = None
        self._tx_queue: asyncio.Queue[bytes] | None = None
        self._rx_queue: asyncio.Queue[bytes] | None = None
        self._run_task: asyncio.Task[Any] | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._needs_enrollment = False
        self.enrolled: EnrolledCert | None = None
        self.connected = False
        self.last_error: str | None = None
        self.last_tx_at: datetime | None = None
        self.last_rx_at: datetime | None = None
        self.sent_count = 0
        self.received_count = 0  # notes actually created
        self.rx_total = 0  # CoT events pulled off the wire, before any filter
        self.rx_filtered = 0  # dropped by type/callsign/echo/dedup/rate

    @property
    def is_running(self) -> bool:
        return self._run_task is not None and not self._run_task.done()

    @property
    def rx_queue(self) -> asyncio.Queue[bytes] | None:
        return self._rx_queue

    @property
    def stale_seconds(self) -> int:
        try:
            return max(1, int(self.settings.get("cot_stale_seconds", 3600)))
        except (TypeError, ValueError):
            return 3600

    @property
    def archive(self) -> bool:
        return bool(self.settings.get("cot_archive", True))

    def _build_config(self) -> Any:
        s = self.settings
        section: dict[str, str] = {}

        def _path(key: str) -> None:
            if s.get(key):
                section_key = {
                    "tls_client_cert": "PYTAK_TLS_CLIENT_CERT",
                    "tls_client_key": "PYTAK_TLS_CLIENT_KEY",
                    "tls_ca_cert": "PYTAK_TLS_CLIENT_CAFILE",
                }[key]
                section[section_key] = os.path.expanduser(str(s[key]))

        package = package_settings(s, tak_dir())
        if package is not None:
            section["COT_URL"] = package.cot_url
            if package.client_cert:
                section["PYTAK_TLS_CLIENT_CERT"] = package.client_cert
                if package.client_password:
                    section["PYTAK_TLS_CLIENT_PASSWORD"] = package.client_password
            if package.ca_pem:
                section["PYTAK_TLS_CLIENT_CAFILE"] = package.ca_pem

        if str(s.get("cot_url") or "").strip():
            section["COT_URL"] = str(s["cot_url"]).strip()
        for key in ("tls_client_cert", "tls_client_key", "tls_ca_cert"):
            _path(key)

        password = _secret(s, "tls_client_password_env", "tls_client_password")
        if password:
            section["PYTAK_TLS_CLIENT_PASSWORD"] = password
        if not bool(s.get("tls_verify", True)):
            section["PYTAK_TLS_DONT_VERIFY"] = "1"
        if not bool(s.get("tls_check_hostname", False)):
            section["PYTAK_TLS_DONT_CHECK_HOSTNAME"] = "1"

        # Enrollment is Oden's job (see oden.tak.enrollment), done in _connect()
        # because it is async. pytak only ever sees the resulting client cert, so
        # PYTAK_TLS_CERT_ENROLLMENT_* are deliberately never set here.
        enroll_user = str(s.get("enroll_username") or "").strip()
        enroll_pw = _secret(s, "enroll_password_env", "enroll_password")
        have_cert = bool(section.get("PYTAK_TLS_CLIENT_CERT"))
        self._needs_enrollment = bool(enroll_user and enroll_pw) and not have_cert
        if not self._needs_enrollment and not have_cert and package is not None and package.needs_enrollment:
            missing = "användarnamn" if not enroll_user else "lösenord"
            raise ValueError(
                f"TAK: data-paketet innehåller bara serverns CA och kräver enrollment, "
                f"men enrollment-{missing} saknas. Fyll i det i TAK-fliken."
            )

        # interpolation=None: passwords are arbitrary text, and BasicInterpolation
        # reads "%" as syntax — a password containing "%s" raises on assignment,
        # with the password in the message.
        parser = ConfigParser(interpolation=None)
        parser["oden_tak"] = {key: _escape_for_pytak(key, value) for key, value in section.items()}
        return parser["oden_tak"]

    async def _ensure_enrolled_cert(self) -> None:
        """Point pytak at our cached (or freshly enrolled) client cert.

        Runs on every (re)connect: a cache hit is one file read, and a cert
        nearing expiry gets renewed without a restart.
        """
        s = self.settings
        host = urlparse(str(self._config.get("COT_URL") or "")).hostname
        if not host:
            raise ValueError("TAK: kunde inte läsa ut värdnamnet ur serveradressen för enrollment")
        self.enrolled = await ensure_cert(
            host,
            str(s.get("enroll_username") or "").strip(),
            _secret(s, "enroll_password_env", "enroll_password"),
            tak_dir(),
        )
        self._config["PYTAK_TLS_CLIENT_CERT"] = _escape_for_pytak("PYTAK_TLS_CLIENT_CERT", self.enrolled.path)
        self._config["PYTAK_TLS_CLIENT_PASSWORD"] = _escape_for_pytak(
            "PYTAK_TLS_CLIENT_PASSWORD", self.enrolled.passphrase
        )

    async def _connect(self) -> None:
        """Open (or re-open) the pytak connection, keeping our queues."""
        import pytak  # optional dependency, imported only when TAK is enabled

        if self._needs_enrollment:
            await self._ensure_enrolled_cert()
        self._clitool = pytak.CLITool(self._config, self._tx_queue, self._rx_queue)
        # First time pytak sizes the queues; every reconnect reuses the same objects.
        self._tx_queue, self._rx_queue = self._clitool.tx_queue, self._clitool.rx_queue
        await asyncio.wait_for(self._clitool.setup(), _CONNECT_TIMEOUT)
        self.connected = True
        self.last_error = None

    async def start(self) -> None:
        if self.is_running:
            return
        self._config = self._build_config()
        if not self._config.get("COT_URL"):
            raise ValueError("TAK: ingen server angiven (sätt cot_url eller pref_package)")

        await self._connect()
        self._run_task = asyncio.create_task(self._run())

        from oden.tak.listener import start_tak_listener

        self._listener_task = start_tak_listener(self)
        logger.info("TAK-bryggan startad (%s)", self._config.get("COT_URL"))

    async def _run(self) -> None:
        """Run pytak until cancelled; on connection loss, reconnect with backoff.

        Queued markers survive the gap (bounded tx queue) and the listener keeps
        waiting on the same rx queue.
        """
        delay = _RECONNECT_MIN
        while True:
            try:
                if not self.connected:
                    await self._connect()
                    delay = _RECONNECT_MIN
                    logger.info("TAK-bryggan återansluten")
                await self._clitool.run()
                self.last_error = "pytak avslutade utan fel"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = safe_error(exc, self.settings)
            self.connected = False
            logger.error("TAK-bryggan: %s — nytt försök om %.0f s", self.last_error, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX)

    async def publish(self, cot: bytes) -> bool:
        """Enqueue one CoT event for transmission. Never blocks the caller.

        Accepted while reconnecting too — the queue is drained once the link is back.
        """
        if not self.is_running or self._tx_queue is None:
            return False
        try:
            self._tx_queue.put_nowait(cot)
        except asyncio.QueueFull:
            logger.warning("TAK: TX-kön är full, släpper CoT-händelse")
            return False
        self.sent_count += 1
        self.last_tx_at = datetime.now(timezone.utc)
        return True

    async def stop(self) -> None:
        from oden.tak.listener import stop_tak_listener

        await stop_tak_listener(self._listener_task)
        self._listener_task = None
        if self._run_task is not None:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._run_task
        self._run_task = None
        self._clitool = None
        self._tx_queue = self._rx_queue = None
        self.connected = False


_bridge: TakBridge | None = None


def get_tak_bridge() -> TakBridge | None:
    return _bridge


async def start_tak_bridge() -> TakBridge | None:
    """Start the bridge if ``tak_settings.enabled``. Safe to call when disabled."""
    global _bridge
    settings = load_tak_settings()
    if not settings.get("enabled"):
        return None

    _bridge = TakBridge(settings)
    try:
        await _bridge.start()
    except ImportError:
        import sys

        if getattr(sys, "frozen", False):
            logger.error("TAK är aktiverat men pytak följde inte med i det här bygget av Oden.")
        else:
            logger.error("TAK är aktiverat men pytak saknas — installera med: pip install 'oden[tak]'")
        _bridge = None
    except Exception as exc:
        message = safe_error(exc, settings)
        logger.error("Kunde inte starta TAK-bryggan: %s", message)
        _bridge.last_error = message
    return _bridge


async def stop_tak_bridge() -> None:
    global _bridge
    if _bridge is not None:
        await _bridge.stop()
        _bridge = None
