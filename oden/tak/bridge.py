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
    "callsign": "ODEN",
    "cot_stale_seconds": 3600,
    "cot_archive": True,
}


def load_tak_settings() -> dict[str, Any]:
    raw = get_config_value(cfg.CONFIG_DB, "tak_settings") or {}
    return {**_DEFAULTS, **raw}


class TakBridge:
    """Owns one pytak ``CLITool`` and its tx/rx queues."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self._clitool: Any = None
        self._run_task: asyncio.Task[Any] | None = None
        self.connected = False
        self.last_error: str | None = None
        self.last_tx_at: datetime | None = None
        self.sent_count = 0

    @property
    def is_running(self) -> bool:
        return self._run_task is not None and not self._run_task.done()

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
                    "pref_package": "PREF_PACKAGE",
                    "tls_client_cert": "PYTAK_TLS_CLIENT_CERT",
                    "tls_client_key": "PYTAK_TLS_CLIENT_KEY",
                    "tls_ca_cert": "PYTAK_TLS_CLIENT_CAFILE",
                }[key]
                section[section_key] = os.path.expanduser(str(s[key]))

        if str(s.get("cot_url") or "").strip():
            section["COT_URL"] = str(s["cot_url"]).strip()
        for key in ("pref_package", "tls_client_cert", "tls_client_key", "tls_ca_cert"):
            _path(key)

        pw_env = str(s.get("tls_client_password_env") or "").strip()
        password = os.environ.get(pw_env, "") if pw_env else str(s.get("tls_client_password") or "")
        if password:
            section["PYTAK_TLS_CLIENT_PASSWORD"] = password
        if not bool(s.get("tls_verify", True)):
            section["PYTAK_TLS_DONT_VERIFY"] = "1"

        parser = ConfigParser()
        parser["oden_tak"] = section
        return parser["oden_tak"]

    async def start(self) -> None:
        if self.is_running:
            return
        import pytak  # optional dependency, imported only when TAK is enabled

        config = self._build_config()
        if "COT_URL" not in config and "PREF_PACKAGE" not in config:
            raise ValueError("TAK: varken cot_url eller pref_package är angivet")

        self._clitool = pytak.CLITool(config)
        await self._clitool.setup()
        self._run_task = asyncio.create_task(self._run())
        self.connected = True
        self.last_error = None
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
