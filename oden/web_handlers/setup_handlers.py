"""
Setup wizard handlers for Oden web GUI.

These handlers manage the first-run configuration wizard,
including Signal account linking and registration.
"""

import asyncio
import contextlib
import io
import json
import logging
import shutil
from pathlib import Path

import qrcode
import qrcode.image.svg
from aiohttp import web

from oden import __version__
from oden.bundle_utils import get_bundle_path
from oden.config import (
    CONFIG_FILE,
    DEFAULT_VAULT_PATH,
    ODEN_HOME,
    save_config,
)
from oden.web_templates import SETUP_HTML_TEMPLATE

logger = logging.getLogger(__name__)

# Global state for the linking process
_linker = None
_link_task = None

# Global state for registration process
_registrar = None


async def setup_handler(request: web.Request) -> web.Response:
    """Serve the setup wizard HTML page."""
    # Try to load from static file first (bundled app)
    bundle_path = get_bundle_path()
    static_file = bundle_path / "static" / "setup.html"

    if static_file.exists():
        return web.FileResponse(static_file)

    # Fallback to inline HTML for development
    return web.Response(text=SETUP_HTML_TEMPLATE.replace("{{version}}", __version__), content_type="text/html")


async def setup_status_handler(request: web.Request) -> web.Response:
    """Return current setup/linking status."""
    global _linker

    # Only fetch accounts if explicitly requested (slow operation)
    include_accounts = request.query.get("accounts") == "true"
    existing_accounts = []

    if include_accounts:
        from oden.signal_manager import get_existing_accounts

        existing_accounts = get_existing_accounts()

    if _linker is None:
        return web.json_response(
            {
                "status": "idle",
                "configured": False,
                "oden_home": str(ODEN_HOME),
                "default_vault": str(DEFAULT_VAULT_PATH),
                "existing_accounts": existing_accounts,
            }
        )

    return web.json_response(
        {
            "status": _linker.status,
            "link_uri": _linker.link_uri,
            "linked_number": _linker.linked_number,
            "error": _linker.error,
            "manual_instructions": _linker.get_manual_instructions() if _linker.status == "timeout" else None,
            "existing_accounts": existing_accounts,
        }
    )


async def setup_start_link_handler(request: web.Request) -> web.Response:
    """Start the Signal account linking process."""
    global _linker, _link_task

    try:
        data = await request.json()
        device_name = data.get("device_name", "Oden")
    except (json.JSONDecodeError, TypeError):
        device_name = "Oden"

    # Import here to avoid circular imports
    from oden.signal_manager import SignalLinker

    # Cancel any existing linking process
    if _linker and _linker.process:
        await _linker.cancel()

    _linker = SignalLinker(device_name=device_name)

    try:
        uri = await _linker.start_link()
        if uri:
            # Generate QR code as SVG
            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(uri)
            qr.make(fit=True)
            img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
            svg_buffer = io.BytesIO()
            img.save(svg_buffer)
            qr_svg = svg_buffer.getvalue().decode("utf-8")

            # Start waiting for link in background
            _link_task = asyncio.create_task(_wait_for_link_background())
            return web.json_response(
                {
                    "success": True,
                    "link_uri": uri,
                    "qr_svg": qr_svg,
                    "status": "waiting",
                }
            )
        else:
            return web.json_response(
                {
                    "success": False,
                    "error": _linker.error or "Kunde inte starta länkning",
                    "status": "error",
                },
                status=500,
            )

    except FileNotFoundError as e:
        return web.json_response(
            {
                "success": False,
                "error": f"signal-cli hittades inte: {e}",
                "status": "error",
            },
            status=500,
        )
    except Exception as e:
        logger.error(f"Error starting link: {e}")
        return web.json_response(
            {
                "success": False,
                "error": str(e),
                "status": "error",
            },
            status=500,
        )


async def _wait_for_link_background():
    """Background task to wait for linking to complete."""
    global _linker
    if _linker:
        await _linker.wait_for_link(timeout=60.0)


async def setup_cancel_link_handler(request: web.Request) -> web.Response:
    """Cancel the linking process."""
    global _linker, _link_task

    if _link_task:
        _link_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _link_task
        _link_task = None

    if _linker:
        await _linker.cancel()
        _linker = None

    return web.json_response({"success": True})


async def setup_save_config_handler(request: web.Request) -> web.Response:
    """Save the setup configuration."""
    global _linker

    try:
        data = await request.json()
        vault_path = data.get("vault_path", str(DEFAULT_VAULT_PATH))
        signal_number = data.get("signal_number", "")
        display_name = data.get("display_name", "oden")

        logger.info(f"Save config request: signal_number={signal_number}, vault_path={vault_path}")

        # Use linked number from _linker only if no number was provided
        if not signal_number and _linker and _linker.linked_number:
            signal_number = _linker.linked_number
            logger.info(f"Using linked number from _linker: {signal_number}")

        if not signal_number or signal_number == "+46XXXXXXXXX":
            return web.json_response(
                {
                    "success": False,
                    "error": "Signal-nummer måste anges",
                },
                status=400,
            )

        # Expand and validate vault path
        vault_path = str(Path(vault_path).expanduser())

        # Create vault directory
        Path(vault_path).mkdir(parents=True, exist_ok=True)

        # Save config
        config_dict = {
            "vault_path": vault_path,
            "signal_number": signal_number,
            "display_name": display_name,
            "append_window_minutes": 30,
            "startup_message": "self",
            "plus_plus_enabled": False,
            "timezone": "Europe/Stockholm",
            "web_enabled": True,
            "web_port": 8080,
        }

        save_config(config_dict)
        logger.info(f"Setup complete. Config saved to {CONFIG_FILE}")

        return web.json_response(
            {
                "success": True,
                "message": "Konfiguration sparad! Oden startar om...",
                "config_path": str(CONFIG_FILE),
            }
        )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error saving setup config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def setup_start_register_handler(request: web.Request) -> web.Response:
    """Start Signal account registration."""
    global _registrar

    try:
        data = await request.json()
        phone_number = data.get("phone_number", "").strip()
        use_voice = data.get("use_voice", False)
        captcha_token = data.get("captcha_token", "").strip() or None

        if not phone_number:
            return web.json_response(
                {"success": False, "error": "Telefonnummer krävs"},
                status=400,
            )

        if not phone_number.startswith("+"):
            return web.json_response(
                {"success": False, "error": "Telefonnummer måste börja med + (t.ex. +46701234567)"},
                status=400,
            )

        # Import here to avoid circular imports
        from oden.signal_manager import SignalRegistrar

        _registrar = SignalRegistrar()
        result = await _registrar.start_register(phone_number, use_voice, captcha_token)

        return web.json_response(result)

    except FileNotFoundError as e:
        return web.json_response(
            {"success": False, "error": f"signal-cli hittades inte: {e}"},
            status=500,
        )
    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error starting registration: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def setup_verify_code_handler(request: web.Request) -> web.Response:
    """Verify registration with received code."""
    global _registrar

    if not _registrar:
        return web.json_response(
            {"success": False, "error": "Ingen registrering pågår"},
            status=400,
        )

    try:
        data = await request.json()
        code = data.get("code", "").strip()

        if not code:
            return web.json_response(
                {"success": False, "error": "Verifieringskod krävs"},
                status=400,
            )

        result = await _registrar.verify(code)
        return web.json_response(result)

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error verifying code: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def setup_install_obsidian_template_handler(request: web.Request) -> web.Response:
    """Install Obsidian template to vault directory."""
    try:
        data = await request.json()
        vault_path = data.get("vault_path", "").strip()

        if not vault_path:
            return web.json_response(
                {"success": False, "error": "Vault-sökväg krävs"},
                status=400,
            )

        # Expand user path
        vault_path = str(Path(vault_path).expanduser())
        obsidian_target = Path(vault_path) / ".obsidian"

        # Check if .obsidian already exists
        if obsidian_target.exists():
            return web.json_response(
                {
                    "success": True,
                    "message": "Obsidian-inställningar finns redan",
                    "skipped": True,
                }
            )

        # Find the obsidian template
        bundle_path = get_bundle_path()
        template_path = bundle_path / "obsidian-template" / ".obsidian"

        # Also check relative path for development
        if not template_path.exists():
            dev_template = Path("./obsidian-template/.obsidian")
            if dev_template.exists():
                template_path = dev_template

        if not template_path.exists():
            return web.json_response(
                {"success": False, "error": "Obsidian-mall hittades inte"},
                status=404,
            )

        # Create vault directory if needed
        Path(vault_path).mkdir(parents=True, exist_ok=True)

        # Copy the template
        shutil.copytree(template_path, obsidian_target)

        logger.info(f"Installed Obsidian template to {obsidian_target}")
        return web.json_response(
            {
                "success": True,
                "message": "Obsidian-inställningar installerade! Aktivera community plugins i Obsidian för att använda Map View.",
                "path": str(obsidian_target),
            }
        )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except PermissionError as e:
        logger.error(f"Permission error installing Obsidian template: {e}")
        return web.json_response(
            {"success": False, "error": f"Behörighetsproblem: {e}"},
            status=500,
        )
    except Exception as e:
        logger.error(f"Error installing Obsidian template: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)
