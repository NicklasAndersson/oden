"""TAK integration handlers for the Oden web GUI.

Status, settings and a one-shot test marker. See docs/PLAN_TAK.md phase 4.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from aiohttp import web

from oden import config as cfg
from oden.config_db import set_config_value
from oden.tak.bridge import cert_expiry, get_tak_bridge, load_tak_settings
from oden.tak.cot import Report, latlon_to_mgrs, report_to_cot
from oden.tak.listener import _INBOUND_DEFAULTS
from oden.web_handlers._helpers import handle_errors, parse_json_body

logger = logging.getLogger(__name__)

CERT_WARN_DAYS = 30

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
    return web.json_response(
        {
            "success": True,
            "message": "TAK-inställningar sparade. Starta om Oden för att ansluta med de nya värdena.",
            "restart_required": True,
        }
    )


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
    )

    if not await bridge.publish(cot):
        return web.json_response({"success": False, "error": "Kunde inte köa CoT (full kö?)"}, status=503)

    return web.json_response(
        {
            "success": True,
            "message": f"Testmarkör ODEN.TEST.{tnr} skickad ({lat:.5f}, {lon:.5f})",
        }
    )
