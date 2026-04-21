"""
Account management handlers for Oden web GUI.

Provides endpoints for listing, linking (adding), activating, and deleting
Signal accounts managed by signal-cli in multi-account daemon mode.
"""

import asyncio
import io
import json
import logging
import shutil
from pathlib import Path

import qrcode
import qrcode.image.svg
from aiohttp import web

from oden import config as cfg
from oden.app_state import get_app_state
from oden.signal_manager import get_existing_accounts, get_signal_data_search_paths
from oden.web_handlers._helpers import (
    handle_errors,
    parse_json_body,
    require_writer,
    update_config_and_reload,
)

logger = logging.getLogger(__name__)

# Background task for finishLink polling
_finish_link_task: asyncio.Task | None = None


async def accounts_list_handler(request: web.Request) -> web.Response:
    """List all signal-cli accounts and mark the active one.

    Use on-disk account data as the source of truth so the UI reflects
    deletions immediately even if a running daemon still has stale state.
    """
    app_state = get_app_state()

    accounts = []
    active_number = cfg.SIGNAL_NUMBER
    connected = bool(app_state.writer)

    for account in get_existing_accounts():
        number = account.get("number")
        if number:
            accounts.append({"number": number, "active": number == active_number})

    # Check if active account is valid
    active_valid = any(a["active"] for a in accounts)

    return web.json_response(
        {
            "accounts": accounts,
            "active_number": active_number,
            "active_valid": active_valid,
            "connected": connected,
        }
    )


def _iter_accounts_files() -> list[Path]:
    """Return all known accounts.json locations, de-duplicated by path."""
    files: list[Path] = []
    seen: set[Path] = set()
    for data_path in get_signal_data_search_paths():
        accounts_file = data_path / "data" / "accounts.json"
        if accounts_file not in seen:
            seen.add(accounts_file)
            files.append(accounts_file)
    return files


def _remove_account_from_disk(number: str) -> bool:
    """Remove an account from all known accounts.json files and directories."""
    removed_any = False

    for accounts_file in _iter_accounts_files():
        if not accounts_file.exists():
            continue

        try:
            data = json.loads(accounts_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Error reading %s while deleting %s: %s", accounts_file, number, e)
            continue

        accounts = data.get("accounts", [])
        matching_entries = [acc for acc in accounts if acc.get("number") == number]
        if not matching_entries:
            continue

        base_data_dir = accounts_file.parent.resolve()
        for account_entry in matching_entries:
            account_path = account_entry.get("path")
            if not account_path:
                continue

            account_dir = (base_data_dir / account_path).resolve()
            if not account_dir.is_relative_to(base_data_dir):
                logger.error(
                    "Refusing to delete account directory outside base path: %s (base: %s)",
                    account_dir,
                    base_data_dir,
                )
                continue

            if account_dir.exists() and account_dir.is_dir():
                shutil.rmtree(account_dir)
                logger.info("Deleted account directory: %s", account_dir)

        data["accounts"] = [acc for acc in accounts if acc.get("number") != number]
        accounts_file.write_text(json.dumps(data, indent=2))
        logger.info("Removed %s from %s", number, accounts_file)
        removed_any = True

    return removed_any


@require_writer
async def accounts_link_handler(request: web.Request) -> web.Response:
    """Start linking a new Signal account via QR code.

    Uses JSON-RPC startLink (multi-account command) and generates a QR code SVG.
    Then starts a background task to call finishLink.
    """
    global _finish_link_task

    app_state = get_app_state()

    # Cancel any existing link task
    if _finish_link_task and not _finish_link_task.done():
        _finish_link_task.cancel()

    # Reset link state
    app_state.link_status = "waiting"
    app_state.link_uri = None
    app_state.linked_number = None
    app_state.link_error = None

    # Call startLink via JSON-RPC (multi-account command, no account param)
    response = await app_state.send_jsonrpc("startLink", timeout=30.0)
    if not response or "result" not in response:
        error_msg = "Kunde inte starta länkning"
        if response and "error" in response:
            error_msg = response["error"].get("message", error_msg)
        app_state.link_status = "error"
        app_state.link_error = error_msg
        return web.json_response(
            {"success": False, "error": error_msg},
            status=500,
        )

    device_link_uri = response["result"].get("deviceLinkUri")
    if not device_link_uri:
        app_state.link_status = "error"
        app_state.link_error = "Ingen länk-URI mottagen"
        return web.json_response(
            {"success": False, "error": "Ingen länk-URI mottagen"},
            status=500,
        )

    app_state.link_uri = device_link_uri

    # Generate QR code SVG
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(device_link_uri)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    svg_buffer = io.BytesIO()
    img.save(svg_buffer)
    qr_svg = svg_buffer.getvalue().decode("utf-8")

    # Start background task for finishLink
    try:
        data = await request.json()
        device_name = data.get("device_name", "Oden")
    except (json.JSONDecodeError, TypeError):
        device_name = "Oden"

    _finish_link_task = asyncio.create_task(_finish_link_background(device_link_uri, device_name))

    return web.json_response(
        {
            "success": True,
            "qr_svg": qr_svg,
            "link_uri": device_link_uri,
            "status": "waiting",
        }
    )


async def _finish_link_background(device_link_uri: str, device_name: str) -> None:
    """Background task: call finishLink and update app_state with the result."""
    app_state = get_app_state()
    try:
        # finishLink can take a long time (user needs to scan QR code)
        response = await app_state.send_jsonrpc(
            "finishLink",
            params={"deviceLinkUri": device_link_uri, "deviceName": device_name},
            timeout=120.0,
        )

        if response and "result" in response:
            number = response["result"].get("number")
            if number:
                app_state.linked_number = number
                app_state.link_status = "linked"
                logger.info(f"Successfully linked account: {number}")
                return

        error_msg = "Länkning misslyckades"
        if response and "error" in response:
            error_msg = response["error"].get("message", error_msg)
        app_state.link_status = "error"
        app_state.link_error = error_msg
        logger.error(f"Link failed: {error_msg}")

    except asyncio.CancelledError:
        app_state.link_status = "idle"
        logger.info("Link task cancelled")
    except Exception as e:
        app_state.link_status = "error"
        app_state.link_error = str(e)
        logger.error(f"Error in finishLink: {e}")


async def accounts_link_status_handler(request: web.Request) -> web.Response:
    """Poll the status of an ongoing account linking process."""
    app_state = get_app_state()
    return web.json_response(
        {
            "status": app_state.link_status,
            "linked_number": app_state.linked_number,
            "error": app_state.link_error,
        }
    )


async def accounts_link_cancel_handler(request: web.Request) -> web.Response:
    """Cancel an ongoing account linking process."""
    global _finish_link_task

    app_state = get_app_state()

    if _finish_link_task and not _finish_link_task.done():
        _finish_link_task.cancel()
        _finish_link_task = None

    app_state.link_status = "idle"
    app_state.link_uri = None
    app_state.linked_number = None
    app_state.link_error = None

    logger.info("Account link cancelled by user")
    return web.json_response({"success": True})


@handle_errors("activate account")
@parse_json_body
async def accounts_activate_handler(request: web.Request) -> web.Response:
    """Set a specific account as the active account."""
    data = request["json_body"]
    number = data.get("number", "").strip()

    if not number:
        return web.json_response(
            {"success": False, "error": "Inget nummer angivet"},
            status=400,
        )

    # Persist to config_db and reload
    update_config_and_reload("signal_number", number)

    # Clear cached groups so they will be refreshed for the newly active account
    app_state = get_app_state()
    app_state.groups = []

    logger.info(f"Active account changed to: {number}")
    return web.json_response(
        {
            "success": True,
            "message": f"Aktivt konto ändrat till {number}",
            "number": number,
        }
    )


@require_writer
async def accounts_delete_handler(request: web.Request) -> web.Response:
    """Delete a Signal account's local data via JSON-RPC deleteLocalAccountData."""
    number = request.match_info.get("number", "").strip()
    if not number:
        return web.json_response(
            {"success": False, "error": "Inget nummer angivet"},
            status=400,
        )

    # Prevent deleting the active account without switching first
    if number == cfg.SIGNAL_NUMBER:
        return web.json_response(
            {"success": False, "error": "Kan inte radera det aktiva kontot. Byt konto först."},
            status=400,
        )

    app_state = get_app_state()

    response = await app_state.send_jsonrpc(
        "deleteLocalAccountData",
        params={"account": number},
        timeout=15.0,
    )

    if response and ("result" in response or response.get("id")):
        if "error" in response:
            error_msg = response["error"].get("message", "Okänt fel")
            return web.json_response(
                {"success": False, "error": error_msg},
                status=500,
            )
        _remove_account_from_disk(number)
        logger.info(f"Deleted local account data for: {number}")
        return web.json_response(
            {
                "success": True,
                "message": f"Kontodata för {number} har raderats",
            }
        )

    return web.json_response(
        {"success": False, "error": "Inget svar från signal-cli"},
        status=500,
    )


async def accounts_force_delete_handler(request: web.Request) -> web.Response:
    """Force-delete account data directly from the filesystem.

    This is the fallback for corrupted accounts where JSON-RPC fails.
    Removes the account directory and its entry from accounts.json.
    """
    number = request.match_info.get("number", "").strip()
    if not number:
        return web.json_response(
            {"success": False, "error": "Inget nummer angivet"},
            status=400,
        )

    if number == cfg.SIGNAL_NUMBER:
        return web.json_response(
            {"success": False, "error": "Kan inte radera det aktiva kontot. Byt konto först."},
            status=400,
        )

    if not _remove_account_from_disk(number):
        return web.json_response(
            {"success": False, "error": f"Kontot {number} hittades inte"},
            status=404,
        )

    return web.json_response(
        {
            "success": True,
            "message": f"Kontodata för {number} har tvångsraderats",
        }
    )


@handle_errors("list devices")
async def accounts_devices_handler(request: web.Request) -> web.Response:
    """List linked devices for the active Signal account."""
    app_state = get_app_state()

    response = await app_state.send_jsonrpc(
        "listDevices",
        params={"account": cfg.SIGNAL_NUMBER},
        timeout=10.0,
    )
    if response and "result" in response:
        return web.json_response({"devices": response["result"]})
    return web.json_response({"devices": []})
