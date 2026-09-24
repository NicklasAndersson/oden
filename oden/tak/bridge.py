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
import warnings
from configparser import ConfigParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from oden import config as cfg
from oden.config_db import get_config_value
from oden.tak.enrollment import EnrolledCert, ensure_cert, write_ca_bundle
from oden.tak.pref_package import package_settings, tak_dir
from oden.tak.redact import redact

logger = logging.getLogger(__name__)

# asyncio.open_connection has no timeout of its own — a blackholed host would
# otherwise hang "Spara" in the GUI forever.
_CONNECT_TIMEOUT = 20.0
# How often the watchdog asks the socket whether the far end has gone away.
# pytak cannot tell us: RXWorker.readcot swallows IncompleteReadError and its
# run loop spins on instead of returning, so CLITool.run() never finishes and
# a dropped link would otherwise burn a core while the GUI still shows green.
_EOF_POLL = 1.0
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
    # Self-position, so operators can address reports *to* Oden. A directed CoT
    # only reaches the callsigns named in <marti><dest>, and ATAK builds that
    # picker from position reports it has seen — publish nothing and Oden is
    # unaddressable. Off by default: it puts an icon on every operator's map.
    "pli_enabled": False,
    "pli_interval_seconds": 60,
    "pli_lat": 0.0,
    "pli_lon": 0.0,
    "pli_team": "Cyan",
    "pli_role": "Team Member",
    "cot_archive": True,
    # Oden's job is to collect: read from TAK, write files for analysis. Pushing
    # our own 7S reports back to TAK as markers (tak_publish) is opt-in.
    "publish_reports": False,
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


def p12_as_pem(path: str, env_name: str) -> tuple[str, str] | None:
    """A ``.p12`` handed over without a password, as ``(cert.pem, key.pem)`` for pytak.

    pytak calls ``str.encode(password)``, so a missing password surfaces as
    ``TypeError: descriptor 'encode' for 'str' objects doesn't apply to a
    'NoneType' object``. A .p12 without a password is opened here instead and
    written as PEM next to the other TAK files (0600); one that has a password
    is a readable error naming the variable to set. Returns None when the file
    cannot be read or ``cryptography`` is missing — pytak reports those itself.
    """
    try:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            pkcs12,
        )
    except ImportError:
        return None
    try:
        blob = Path(path).read_bytes()
    except OSError:
        return None
    try:
        key, cert, _chain = pkcs12.load_key_and_certificates(blob, None)
    except ValueError:
        where = f"miljövariabeln {env_name}" if env_name else "en miljövariabel under Miljövariabel för certlösenord"
        raise ValueError(
            f"TAK: klientcertifikatet {Path(path).name} är lösenordsskyddat (eller trasigt) och inget lösenord är satt. "
            f"Sätt {where} i Odens miljö och starta om Oden."
        ) from None
    if key is None or cert is None:
        raise ValueError(f"TAK: {Path(path).name} innehåller inget klientcertifikat med nyckel")

    dest_dir = tak_dir()
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stem = Path(path).stem
    cert_pem = dest_dir / f"{stem}.cert.pem"
    key_pem = dest_dir / f"{stem}.key.pem"
    for target, data in (
        (cert_pem, cert.public_bytes(Encoding.PEM)),
        (key_pem, key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())),
    ):
        target.write_bytes(data)
        target.chmod(0o600)
    return str(cert_pem), str(key_pem)


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
        self._reader: Any = None  # pytak's RXWorker reader, for the EOF watchdog
        self._run_task: asyncio.Task[Any] | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._pli_task: asyncio.Task[None] | None = None
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
    def pytak_config(self) -> Any:
        """The resolved connection config — server URL, client cert, CA.

        The file-store poller authenticates with exactly what the CoT connection
        already settled on, rather than resolving the package and cert a second
        time. None until :meth:`start` has run.
        """
        return self._config

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
        client_cert = section.get("PYTAK_TLS_CLIENT_CERT", "")
        if client_cert.lower().endswith((".p12", ".pfx")) and not section.get("PYTAK_TLS_CLIENT_PASSWORD"):
            pem = p12_as_pem(client_cert, str(s.get("tls_client_password_env") or "").strip())
            if pem is not None:
                section["PYTAK_TLS_CLIENT_CERT"], section["PYTAK_TLS_CLIENT_KEY"] = pem
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
        # No CA configured (typical after a QR enrollment): trust the CA the
        # server handed out with our cert, as ATAK does, instead of failing
        # verification against the system roots.
        if not self._config.get("PYTAK_TLS_CLIENT_CAFILE"):
            try:
                ca_path = write_ca_bundle(self.enrolled)
            except Exception as exc:
                logger.warning("TAK: kunde inte läsa CA-kedjan ur enrollment-certet: %s", exc)
                ca_path = None
            if ca_path:
                self._config["PYTAK_TLS_CLIENT_CAFILE"] = _escape_for_pytak("PYTAK_TLS_CLIENT_CAFILE", ca_path)
                logger.info("TAK: verifierar servern mot CA:n från enrollment (%s)", ca_path)

    async def _connect(self) -> None:
        """Open (or re-open) the pytak connection, keeping our queues."""
        import pytak  # optional dependency, imported only when TAK is enabled

        if self._needs_enrollment:
            await self._ensure_enrolled_cert()
        if self._config.get("PYTAK_TLS_DONT_CHECK_HOSTNAME"):
            # Our documented default (TAK certs rarely name the address you dial),
            # so pytak's warnings.warn about it is noise. The DONT_VERIFY warning
            # is left alone: turning CA verification off *should* be loud.
            warnings.filterwarnings(
                "ignore", message="Disabled TLS Server Common Name Verification", category=UserWarning
            )
        self._clitool = pytak.CLITool(self._config, self._tx_queue, self._rx_queue)
        # First time pytak sizes the queues; every reconnect reuses the same objects.
        self._tx_queue, self._rx_queue = self._clitool.tx_queue, self._clitool.rx_queue
        await asyncio.wait_for(self._clitool.setup(), _CONNECT_TIMEOUT)
        self._reader = next(
            (r for r in (getattr(w, "reader", None) for w in getattr(self._clitool, "tasks", ())) if r is not None),
            None,
        )
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
        self._pli_task = self._start_self_pli()
        logger.info("TAK-bryggan startad (%s)", self._config.get("COT_URL"))

    def _start_self_pli(self) -> asyncio.Task[None] | None:
        """Start publishing Oden's own position, if configured. Returns the task, or None."""
        s = self.settings
        if not bool(s.get("pli_enabled")):
            return None
        try:
            lat, lon = float(s.get("pli_lat") or 0.0), float(s.get("pli_lon") or 0.0)
        except (TypeError, ValueError):
            lat = lon = 0.0
        if not (lat or lon):
            logger.warning("TAK: självrapportering är på men saknar position — sätt pli_lat/pli_lon")
            return None
        return asyncio.create_task(self._publish_self_pli(lat, lon))

    async def _publish_self_pli(self, lat: float, lon: float) -> None:
        """Publish a PLI on a fixed cadence until cancelled.

        Queued through the normal tx path, so a reconnect just delays the next one
        rather than dropping the identity: the marker stays valid until ``stale``,
        which is two intervals out.
        """
        from oden.tak.cot import self_pli_cot

        s = self.settings
        interval = max(10.0, float(s.get("pli_interval_seconds") or 60))
        callsign = str(s.get("callsign") or "ODEN")
        team, role = str(s.get("pli_team") or "Cyan"), str(s.get("pli_role") or "Team Member")
        logger.info(
            "TAK: rapporterar egen position som %s (%s/%s) var %.0f s — nu går det att adressera rapporter till Oden",
            callsign,
            team,
            role,
            interval,
        )
        while True:
            try:
                # Stale two intervals out, so one missed publish does not make the
                # contact vanish from everyone's list.
                await self.publish(
                    self_pli_cot(
                        callsign=callsign,
                        lat=lat,
                        lon=lon,
                        team=team,
                        role=role,
                        stale_seconds=int(interval * 2),
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("TAK: kunde inte skicka egen positionsrapport (%r)", exc)
            await asyncio.sleep(interval)

    async def _watch_for_eof(self) -> None:
        """Return once the far end has closed the connection.

        pytak never reports this: ``RXWorker.readcot`` turns the
        ``IncompleteReadError`` at EOF into ``None`` and its ``while True`` loop
        immediately tries again, so it spins at tens of thousands of reads a
        second and ``CLITool.run()`` never returns. Asking the reader directly
        is what turns a dead link back into a reconnect.
        """
        reader = self._reader
        if reader is None or not hasattr(reader, "at_eof"):
            await asyncio.Event().wait()  # nothing to watch: let pytak decide
            return
        while not reader.at_eof():
            await asyncio.sleep(_EOF_POLL)

    async def _teardown_clitool(self) -> None:
        """Stop pytak's worker tasks and drop the CLITool.

        Cancelling the task that awaits ``CLITool.run()`` is not enough:
        ``asyncio.wait`` does not cancel what it waits on, so the TX/RX workers
        survive, and after a dropped link they survive *spinning*. The TAK tab
        stops and starts the bridge on every save, so one leak per save adds up.
        """
        clitool, self._clitool, self._reader = self._clitool, None, None
        if clitool is None:
            return
        tasks = [t for t in getattr(clitool, "running_tasks", ()) or () if not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self) -> None:
        """Run pytak until cancelled; on connection loss, reconnect with backoff.

        Queued markers survive the gap (bounded tx queue) and the listener keeps
        waiting on the same rx queue.
        """
        delay = _RECONNECT_MIN
        while True:
            runner: asyncio.Task[Any] | None = None
            watchdog: asyncio.Task[None] | None = None
            try:
                if not self.connected:
                    await self._connect()
                    delay = _RECONNECT_MIN
                    logger.info("TAK-bryggan återansluten")
                runner = asyncio.create_task(self._clitool.run())
                watchdog = asyncio.create_task(self._watch_for_eof())
                done, _ = await asyncio.wait({runner, watchdog}, return_when=asyncio.FIRST_COMPLETED)
                if runner in done:
                    runner.result()  # raises whatever pytak failed with
                    self.last_error = "pytak avslutade utan fel"
                else:
                    self.last_error = "servern stängde anslutningen"
            except asyncio.CancelledError:
                await self._cancel(runner, watchdog)
                await self._teardown_clitool()
                raise
            except Exception as exc:
                self.last_error = safe_error(exc, self.settings)
            await self._cancel(runner, watchdog)
            # A new CLITool is built on reconnect, so this one's workers have to
            # go now or they keep the old socket and spin on it forever.
            await self._teardown_clitool()
            self.connected = False
            logger.error("TAK-bryggan: %s — nytt försök om %.0f s", self.last_error, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX)

    @staticmethod
    async def _cancel(*tasks: asyncio.Task[Any] | None) -> None:
        pending = [t for t in tasks if t is not None and not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

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
        if self._pli_task is not None and not self._pli_task.done():
            self._pli_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pli_task
        self._pli_task = None
        if self._run_task is not None:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._run_task
        self._run_task = None
        await self._teardown_clitool()
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
