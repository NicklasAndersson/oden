"""Connect (or disconnect) Signal from the Signal tab.

Replaces the old first-run wizard. When Oden runs without Signal there is no
signal-cli daemon, so linking and registration run signal-cli standalone
(``SignalLinker`` / ``SignalRegistrar``), exactly as the wizard did. Once an
account exists, ``use`` makes it Oden's account and turns Signal on; the
choice is read at startup, so Oden has to be restarted to start listening.

With Signal already running, further accounts are linked through the daemon
under Signal → Konton (``account_handlers``) instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
from typing import Any

import qrcode
import qrcode.image.svg
from aiohttp import web

from oden import config as cfg
from oden.config_db import get_all_config, set_config_value
from oden.path_utils import ensure_directory
from oden.web_handlers._helpers import handle_errors, parse_json_body

logger = logging.getLogger(__name__)

_LINK_TIMEOUT = 60.0
_RESTART_NOTE = "Starta om Oden för att börja ta emot meddelanden."

_linker: Any = None
_link_task: asyncio.Task | None = None
_registrar: Any = None


def _daemon_running() -> bool:
    from oden.app_state import get_app_state

    return get_app_state().writer is not None


def _qr_svg(uri: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    buffer = io.BytesIO()
    qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(buffer)
    return buffer.getvalue().decode("utf-8")


def _ensure_signal_data() -> str | None:
    ok, error = ensure_directory(cfg.SIGNAL_DATA_PATH)
    return None if ok else f"Kunde inte skapa signal-data-katalogen: {error}"


def _account_error(number: str) -> str | None:
    """Why *number* cannot be used as Oden's account, or None."""
    if not number or number.startswith("+46XXXX"):
        return "Ange ett Signal-nummer"
    from oden.signal_manager import get_existing_accounts

    try:
        accounts = get_existing_accounts()
    except Exception as exc:
        logger.warning("Could not read signal-cli accounts: %s", exc)
        return "Kunde inte läsa signal-cli:s konton."
    numbers = [a["number"] for a in accounts]
    if number not in numbers:
        known = ", ".join(numbers) or "inga"
        return f"Numret {number} finns inte bland signal-cli:s konton (tillgängliga: {known})."
    return None


@handle_errors("signal connect status")
async def signal_connect_status_handler(request: web.Request) -> web.Response:
    """Signal state for the Signal tab: on/off, why off, running link, existing accounts."""
    stored = get_all_config(cfg.CONFIG_DB)
    payload: dict[str, Any] = {
        "signal_enabled": bool(cfg.SIGNAL_ENABLED),
        "signal_enabled_setting": bool(stored.get("signal_enabled", True)),
        "signal_number": stored.get("signal_number") or "",
        "off_reason": cfg.SIGNAL_OFF_REASON,
        "daemon_running": _daemon_running(),
        "link": None,
        "accounts": [],
    }
    if _linker is not None:
        payload["link"] = {
            "status": _linker.status,
            "linked_number": _linker.linked_number,
            "error": _linker.error,
            "manual_instructions": _linker.get_manual_instructions() if _linker.status == "timeout" else None,
        }
    if request.query.get("accounts") == "1":
        from oden.signal_manager import get_existing_accounts

        with contextlib.suppress(Exception):
            payload["accounts"] = get_existing_accounts()
    return web.json_response(payload)


async def _wait_for_link() -> None:
    if _linker is not None:
        await _linker.wait_for_link(timeout=_LINK_TIMEOUT)


async def _stop_linking() -> None:
    global _linker, _link_task
    if _link_task is not None:
        _link_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _link_task
        _link_task = None
    if _linker is not None:
        await _linker.cancel()
        _linker = None


@handle_errors("signal link start")
async def signal_link_start_handler(request: web.Request) -> web.Response:
    """Show a QR code that links Oden as a device on an existing Signal account."""
    global _linker, _link_task
    if _daemon_running():
        return web.json_response(
            {"success": False, "error": "Signal körs redan — länka fler konton under Signal → Konton."},
            status=409,
        )
    error = _ensure_signal_data()
    if error:
        return web.json_response({"success": False, "error": error}, status=500)

    from oden.signal_linker import SignalLinker

    await _stop_linking()
    _linker = SignalLinker(device_name=cfg.DISPLAY_NAME or "Oden")
    try:
        uri = await _linker.start_link()
    except FileNotFoundError as exc:
        return web.json_response({"success": False, "error": f"signal-cli hittades inte: {exc}"}, status=500)
    if not uri:
        return web.json_response({"success": False, "error": _linker.error or "Kunde inte starta länkning"}, status=500)
    _link_task = asyncio.create_task(_wait_for_link())
    return web.json_response({"success": True, "link_uri": uri, "qr_svg": _qr_svg(uri), "status": "waiting"})


@handle_errors("signal link cancel")
async def signal_link_cancel_handler(request: web.Request) -> web.Response:
    await _stop_linking()
    return web.json_response({"success": True})


@handle_errors("signal register start")
@parse_json_body
async def signal_register_start_handler(request: web.Request) -> web.Response:
    """Register a new number (SMS/voice, CAPTCHA when Signal asks for one)."""
    global _registrar
    if _daemon_running():
        return web.json_response({"success": False, "error": "Signal körs redan."}, status=409)

    data = request["json_body"]
    phone_number = str(data.get("phone_number") or "").strip()
    if not phone_number.startswith("+"):
        return web.json_response(
            {"success": False, "error": "Telefonnummer måste börja med + (t.ex. +46701234567)"}, status=400
        )
    error = _ensure_signal_data()
    if error:
        return web.json_response({"success": False, "error": error}, status=500)

    from oden.signal_registrar import SignalRegistrar

    _registrar = SignalRegistrar()
    try:
        result = await _registrar.start_register(
            phone_number, bool(data.get("use_voice")), str(data.get("captcha_token") or "").strip() or None
        )
    except FileNotFoundError as exc:
        return web.json_response({"success": False, "error": f"signal-cli hittades inte: {exc}"}, status=500)
    return web.json_response(result)


@handle_errors("signal register verify")
@parse_json_body
async def signal_register_verify_handler(request: web.Request) -> web.Response:
    if _registrar is None:
        return web.json_response({"success": False, "error": "Ingen registrering pågår"}, status=400)
    code = str(request["json_body"].get("code") or "").strip()
    if not code:
        return web.json_response({"success": False, "error": "Verifieringskod krävs"}, status=400)
    return web.json_response(await _registrar.verify(code))


@handle_errors("signal use account")
@parse_json_body
async def signal_use_account_handler(request: web.Request) -> web.Response:
    """Make an existing signal-cli account Oden's account and turn Signal on."""
    number = str(request["json_body"].get("signal_number") or "").strip()
    error = _account_error(number)
    if error:
        return web.json_response({"success": False, "error": error}, status=400)

    set_config_value(cfg.CONFIG_DB, "signal_number", number)
    set_config_value(cfg.CONFIG_DB, "signal_enabled", True)
    await _stop_linking()
    logger.info("Signal kopplat till %s via webbgränssnittet", number)
    return web.json_response(
        {"success": True, "restart_required": True, "message": f"Signal kopplat till {number}. {_RESTART_NOTE}"}
    )


@handle_errors("signal disable")
async def signal_disable_handler(request: web.Request) -> web.Response:
    """Run Oden without Signal (e.g. TAK only). The linked account stays in signal-cli."""
    set_config_value(cfg.CONFIG_DB, "signal_enabled", False)
    logger.info("Signal avstängt via webbgränssnittet")
    return web.json_response(
        {
            "success": True,
            "restart_required": True,
            "message": "Signal avstängt. Starta om Oden för att stänga signal-cli.",
        }
    )
