"""pytak-backed connection to a TAK Server.

Phase 2: outbound only — Oden report -> CoT marker. The inbound listener
(phase 3) attaches an rx task to the same ``CLITool``.

``pytak`` is an optional dependency (``oden[tak]``); it is imported lazily inside
``TakBridge.start`` so nothing here is required unless TAK is enabled.

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

from oden import config as cfg
from oden.config_db import get_config_value

logger = logging.getLogger(__name__)

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
    # The password is read from the env var named here, never stored.
    "enroll_username": "",
    "enroll_password_env": "ODEN_TAK_ENROLL_PASSWORD",
    "callsign": "ODEN",
    "cot_stale_seconds": 3600,
    "cot_archive": True,
    # inbound defaults live in oden.tak.listener._INBOUND_DEFAULTS
}


def load_tak_settings() -> dict[str, Any]:
    raw = get_config_value(cfg.CONFIG_DB, "tak_settings") or {}
    return {**_DEFAULTS, **raw}


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
            pw_env = str(settings.get("tls_client_password_env") or "").strip()
            password = os.environ.get(pw_env, "") if pw_env else str(settings.get("tls_client_password") or "")
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
        self._clitool: Any = None
        self._run_task: asyncio.Task[Any] | None = None
        self._listener_task: asyncio.Task[None] | None = None
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
    def rx_queue(self) -> Any:
        return getattr(self._clitool, "rx_queue", None)

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

        pref_package = os.path.expanduser(str(s.get("pref_package") or "").strip())
        if pref_package:
            # Unzips the data package, converts the .p12s to PEM and fills in
            # COT_URL + PYTAK_TLS_CLIENT_CERT/KEY/CAFILE from the .pref inside.
            import pytak

            section.update({k: str(v) for k, v in pytak.read_pref_package(pref_package).items() if v})

        if str(s.get("cot_url") or "").strip():
            section["COT_URL"] = str(s["cot_url"]).strip()
        for key in ("tls_client_cert", "tls_client_key", "tls_ca_cert"):
            _path(key)

        pw_env = str(s.get("tls_client_password_env") or "").strip()
        password = os.environ.get(pw_env, "") if pw_env else str(s.get("tls_client_password") or "")
        if password:
            section["PYTAK_TLS_CLIENT_PASSWORD"] = password
        if not bool(s.get("tls_verify", True)):
            section["PYTAK_TLS_DONT_VERIFY"] = "1"
        if not bool(s.get("tls_check_hostname", False)):
            section["PYTAK_TLS_DONT_CHECK_HOSTNAME"] = "1"

        enroll_user = str(s.get("enroll_username") or "").strip()
        if enroll_user:
            enroll_pw_env = str(s.get("enroll_password_env") or "").strip()
            enroll_pw = os.environ.get(enroll_pw_env, "") if enroll_pw_env else ""
            section["PYTAK_TLS_CERT_ENROLLMENT_USERNAME"] = enroll_user
            if enroll_pw:
                section["PYTAK_TLS_CERT_ENROLLMENT_PASSWORD"] = enroll_pw

        parser = ConfigParser()
        parser["oden_tak"] = section
        return parser["oden_tak"]

    async def start(self) -> None:
        if self.is_running:
            return
        import pytak  # optional dependency, imported only when TAK is enabled

        config = self._build_config()
        if not config.get("COT_URL"):
            raise ValueError("TAK: ingen server angiven (sätt cot_url eller pref_package)")

        self._clitool = pytak.CLITool(config)
        await self._clitool.setup()
        self._run_task = asyncio.create_task(self._run())
        self.connected = True
        self.last_error = None

        from oden.tak.listener import start_tak_listener

        self._listener_task = start_tak_listener(self)
        logger.info("TAK-bryggan startad (%s)", config.get("COT_URL", "pref_package"))

    async def _run(self) -> None:
        try:
            await self._clitool.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - network path
            self.connected = False
            self.last_error = repr(exc)
            logger.error("TAK-bryggan stannade: %r", exc)

    async def publish(self, cot: bytes) -> bool:
        """Enqueue one CoT event for transmission. Never blocks the caller."""
        if not self.is_running or self._clitool is None:
            return False
        try:
            self._clitool.tx_queue.put_nowait(cot)
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
        logger.error("Kunde inte starta TAK-bryggan: %r", exc)
        _bridge.last_error = repr(exc)
    return _bridge


async def stop_tak_bridge() -> None:
    global _bridge
    if _bridge is not None:
        await _bridge.stop()
        _bridge = None
