"""TAK integration handlers for the Oden web GUI.

Status, settings and a one-shot test marker. See docs/PLAN_TAK.md phase 4.
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import zipfile
from pathlib import Path
from typing import Any

from aiohttp import web

from oden import config as cfg
from oden.config_db import set_config_value
from oden.tak.bridge import cert_expiry, get_tak_bridge, load_tak_settings
from oden.tak.cot import Report, latlon_to_mgrs, report_to_cot, sanitize_token
from oden.tak.listener import _INBOUND_DEFAULTS
from oden.web_handlers._helpers import handle_errors, parse_json_body

logger = logging.getLogger(__name__)

CERT_WARN_DAYS = 30
MAX_PACKAGE_BYTES = 5 * 1024 * 1024  # data packages are ~30 KB; 5 MB is generous

# Settings the form may write. tls_client_password is deliberately absent — the
# password comes from the environment variable named by tls_client_password_env,
# so it never lands in the config db or in an HTTP response.
_EDITABLE_KEYS = {
    "enabled": bool,
    "cot_url": str,
    "pref_package": str,
    "tls_client_cert": str,
    "tls_client_key": str,
    "tls_client_password_env": str,
    "tls_ca_cert": str,
    "tls_verify": bool,
    "tls_check_hostname": bool,
    "enroll_username": str,
    "enroll_password_env": str,
    "callsign": str,
    "cot_stale_seconds": int,
    "cot_archive": bool,
    "inbound_enabled": bool,
    "inbound_types": list,
    "inbound_callsign_allow": list,
    "inbound_callsign_deny": list,
    "inbound_min_move_m": float,
    "inbound_max_per_minute": int,
    "inbound_group_name": str,
}


def _coerce(value: Any, kind: type) -> Any:
    if kind is bool:
        return bool(value)
    if kind is list:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return [str(part).strip() for part in (value or []) if str(part).strip()]
    if kind in (int, float):
        try:
            return kind(value)
        except (TypeError, ValueError):
            return kind(0)
    return str(value or "")


async def tak_settings_handler(request: web.Request) -> web.Response:
    """Current TAK settings. Never returns a password."""
    settings = {**_INBOUND_DEFAULTS, **load_tak_settings()}
    return web.json_response({key: settings.get(key) for key in _EDITABLE_KEYS})


@handle_errors("save tak settings")
@parse_json_body
async def tak_settings_save_handler(request: web.Request) -> web.Response:
    data = request["json_body"]
    stored = load_tak_settings()

    updates = {key: _coerce(data[key], kind) for key, kind in _EDITABLE_KEYS.items() if key in data}
    merged = {**stored, **updates}

    if merged.get("enabled") and not (merged.get("cot_url") or merged.get("pref_package")):
        return web.json_response(
            {"success": False, "error": "Ange cot_url eller pref_package innan TAK aktiveras"},
            status=400,
        )
    if merged.get("cot_stale_seconds", 0) < 1:
        return web.json_response({"success": False, "error": "cot_stale_seconds måste vara minst 1"}, status=400)

    set_config_value(cfg.CONFIG_DB, "tak_settings", merged)
    logger.info("TAK-inställningar sparade via web-GUI")

    from oden.app_state import get_app_state

    # Reconnect with the new settings so the operator doesn't have to restart —
    # but only when Oden's main lifecycle is actually running (not under tests).
    if get_app_state().loop is None:
        return web.json_response(
            {"success": True, "message": "TAK-inställningar sparade. Starta om Oden för att tillämpa dem."}
        )

    from oden.tak.bridge import get_tak_bridge, start_tak_bridge, stop_tak_bridge

    try:
        await stop_tak_bridge()
        await start_tak_bridge()
    except Exception as exc:  # pragma: no cover - network path
        logger.warning("TAK: kunde inte återansluta efter sparande: %r", exc)

    bridge = get_tak_bridge()
    if not merged.get("enabled"):
        message = "TAK-inställningar sparade. TAK är avstängt."
    elif bridge is not None and bridge.is_running:
        message = "TAK-inställningar sparade och ansluten."
    else:
        err = getattr(bridge, "last_error", None)
        message = f"Sparat, men anslutningen misslyckades: {err}" if err else "Sparat, men kunde inte ansluta."

    return web.json_response({"success": True, "message": message})


@handle_errors("tak status")
async def tak_status_handler(request: web.Request) -> web.Response:
    settings = load_tak_settings()
    bridge = get_tak_bridge()
    expiry = cert_expiry(settings)

    days_left = None
    if expiry is not None:
        days_left = (expiry - dt.datetime.now(dt.timezone.utc)).days

    return web.json_response(
        {
            "enabled": bool(settings.get("enabled")),
            "connected": bool(bridge is not None and bridge.is_running),
            "cot_url": settings.get("cot_url") or settings.get("pref_package") or "",
            "inbound_enabled": bool(settings.get("inbound_enabled")),
            "sent_count": getattr(bridge, "sent_count", 0),
            "received_count": getattr(bridge, "received_count", 0),
            "last_tx_at": (bridge.last_tx_at.isoformat() if bridge and bridge.last_tx_at else None),
            "last_error": getattr(bridge, "last_error", None),
            "cert_expires_at": expiry.isoformat() if expiry else None,
            "cert_days_left": days_left,
            "cert_warning": days_left is not None and days_left < CERT_WARN_DAYS,
        }
    )


@handle_errors("send tak test cot")
@parse_json_body
async def tak_test_handler(request: web.Request) -> web.Response:
    """Send one test marker so the operator can verify the connection."""
    bridge = get_tak_bridge()
    if bridge is None or not bridge.is_running:
        return web.json_response({"success": False, "error": "TAK-bryggan är inte ansluten"}, status=503)

    data = request["json_body"]
    mgrs_str = str(data.get("mgrs") or "").strip()
    if not mgrs_str:
        return web.json_response({"success": False, "error": "Ange en MGRS-position"}, status=400)

    from oden.pipelines.seven_s import _mgrs_to_latlon

    coords = _mgrs_to_latlon(mgrs_str)
    if coords is None:
        return web.json_response({"success": False, "error": f"Kunde inte tolka MGRS: {mgrs_str}"}, status=400)

    lat, lon = coords
    now = dt.datetime.now(dt.timezone.utc)
    tnr = now.strftime("%d%H%M")
    cot = report_to_cot(
        Report(
            report_type="TEST",
            tnr=tnr,
            lat=lat,
            lon=lon,
            event_time=now,
            start_time=now,
            remarks=f"Oden testmarkör {latlon_to_mgrs(lat, lon) or mgrs_str}",
        ),
        stale_seconds=bridge.stale_seconds,
        archive=bridge.archive,
        callsign=str(getattr(bridge, "settings", {}).get("callsign") or ""),
    )

    if not await bridge.publish(cot):
        return web.json_response({"success": False, "error": "Kunde inte köa CoT (full kö?)"}, status=503)

    return web.json_response(
        {
            "success": True,
            "message": f"Testmarkör ODEN.TEST.{tnr} skickad ({lat:.5f}, {lon:.5f})",
        }
    )


@handle_errors("upload tak package")
async def tak_upload_package_handler(request: web.Request) -> web.Response:
    """Store an uploaded ATAK data package under ODEN_HOME/tak and return its path.

    Lets the GUI file picker deliver a .zip when the browser can't hand over the
    real filesystem path. Contains private keys, so the file lands 0600 in a 0700
    directory alongside config.db.
    """
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"success": False, "error": "Ingen fil skickades"}, status=400)

    filename = Path(field.filename or "").name
    if not filename.lower().endswith(".zip"):
        return web.json_response({"success": False, "error": "Filen måste vara en .zip"}, status=400)

    blob = b""
    while chunk := await field.read_chunk():
        blob += chunk
        if len(blob) > MAX_PACKAGE_BYTES:
            return web.json_response({"success": False, "error": "Filen är för stor (max 5 MB)"}, status=413)

    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return web.json_response({"success": False, "error": "Filen är inte en giltig zip"}, status=400)
    if not any(n.lower().endswith(".pref") for n in names):
        return web.json_response(
            {"success": False, "error": "Zip:en ser inte ut som en TAK-data-package (ingen .pref-fil)"},
            status=400,
        )

    tak_dir = Path(cfg.ODEN_HOME) / "tak"
    tak_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest = tak_dir / f"{sanitize_token(filename[:-4], max_len=64)}.zip"
    dest.write_bytes(blob)
    dest.chmod(0o600)

    logger.info("TAK: data package sparad till %s (%d bytes)", dest, len(blob))
    return web.json_response({"success": True, "path": str(dest)})
