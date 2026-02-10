"""
Setup wizard handlers for Oden web GUI.

These handlers manage the first-run configuration wizard,
including Signal account linking and registration, and
config directory selection with optional INI migration.
"""

import asyncio
import contextlib
import io
import json
import logging
import shutil
from pathlib import Path

import aiohttp_jinja2
import qrcode
import qrcode.image.svg
from aiohttp import web

from oden import __version__
from oden.bundle_utils import (
    DEFAULT_ODEN_HOME,
    get_bundle_path,
    get_oden_home_path,
    validate_oden_home,
)
from oden.config import (
    CONFIG_DB,
    DEFAULT_VAULT_PATH,
    is_configured,
    save_config,
    setup_oden_home,
    soft_reset_config,
)
from oden.path_utils import (
    is_filesystem_root,
    is_within_directory,
    normalize_path,
    validate_ini_file_path,
)

logger = logging.getLogger(__name__)

# Global state for the linking process
_linker = None
_link_task = None

# Global state for registration process
_registrar = None


async def setup_handler(request: web.Request) -> web.Response:
    """Serve the setup wizard HTML page."""
    return aiohttp_jinja2.render_template("setup.html", request, {"version": __version__})


async def setup_status_handler(request: web.Request) -> web.Response:
    """Return current setup/linking status."""
    global _linker

    # Only fetch accounts if explicitly requested (slow operation)
    include_accounts = request.query.get("accounts") == "true"
    existing_accounts = []

    if include_accounts:
        from oden.signal_manager import get_existing_accounts

        try:
            existing_accounts = get_existing_accounts()
            logger.info(f"Found {len(existing_accounts)} existing Signal accounts")
        except Exception as e:
            logger.exception(f"Error getting existing accounts: {e}")
            existing_accounts = []

    # Check configuration status
    configured, config_error = is_configured()

    # Get current oden_home from pointer file
    current_oden_home = get_oden_home_path()

    # Check for recovery candidate: pointer file missing but config.db exists
    recovery_candidate = None
    if config_error == "no_pointer":
        candidate_db = DEFAULT_ODEN_HOME / "config.db"
        if candidate_db.exists():
            is_valid, _db_error = validate_oden_home(DEFAULT_ODEN_HOME)
            if is_valid:
                recovery_candidate = str(DEFAULT_ODEN_HOME)
                logger.warning(
                    "Pointer file missing — found existing config at %s",
                    DEFAULT_ODEN_HOME,
                )

    # Check for existing INI file - first in default location, then in bundle location
    default_ini_path = DEFAULT_ODEN_HOME / "config.ini"
    bundle_ini_path = get_bundle_path() / "config.ini"

    existing_ini_path = None
    if default_ini_path.exists():
        existing_ini_path = default_ini_path
        logger.debug(f"Found config.ini at default location: {default_ini_path}")
    elif bundle_ini_path.exists():
        existing_ini_path = bundle_ini_path
        logger.debug(f"Found config.ini at bundle location: {bundle_ini_path}")

    has_existing_ini = existing_ini_path is not None

    # Read INI content for migration preview
    existing_ini_content = None
    if has_existing_ini:
        try:
            existing_ini_content = existing_ini_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not read INI file for preview: {e}")

    if _linker is None:
        return web.json_response(
            {
                "status": "idle",
                "configured": configured,
                "config_error": config_error,
                "oden_home": str(current_oden_home) if current_oden_home else str(DEFAULT_ODEN_HOME),
                "default_oden_home": str(DEFAULT_ODEN_HOME),
                "default_vault": str(DEFAULT_VAULT_PATH),
                "has_existing_ini": has_existing_ini,
                "existing_ini_path": str(existing_ini_path) if has_existing_ini else None,
                "existing_ini_content": existing_ini_content,
                "existing_accounts": existing_accounts,
                "recovery_candidate": recovery_candidate,
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
            "configured": configured,
            "config_error": config_error,
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


async def setup_oden_home_handler(request: web.Request) -> web.Response:
    """Set up the Oden home directory with optional INI migration."""
    try:
        data = await request.json()
        oden_home_path = data.get("oden_home", str(DEFAULT_ODEN_HOME))
        ini_path_value = data.get("ini_path")  # Optional path to migrate from

        ini_path_obj: Path | None = None
        if ini_path_value:
            # Try validating INI file path - first within home dir, then within bundle
            ini_path_obj, ini_error = validate_ini_file_path(ini_path_value)
            if ini_error:
                # If home validation failed, try bundle location
                bundle_path = get_bundle_path()
                ini_path_obj, bundle_error = validate_ini_file_path(ini_path_value, must_be_within=bundle_path)
                if bundle_error:
                    # Both failed - return the original error
                    return web.json_response(
                        {"success": False, "error": ini_error},
                        status=400,
                    )
                logger.info(f"Using config.ini from bundle location: {ini_path_obj}")

        # Validate and set up; primary path validation is handled inside setup_oden_home
        success, error = setup_oden_home(Path(oden_home_path), ini_path_obj)

        if success:
            logger.info("Oden home directory set to: %s", oden_home_path)
            return web.json_response(
                {
                    "success": True,
                    "message": "Konfigurationskatalog skapad",
                    "oden_home": oden_home_path,
                    "migrated_from_ini": ini_path_obj is not None,
                }
            )
        else:
            return web.json_response(
                {"success": False, "error": error},
                status=400,
            )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error setting up oden home: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def setup_validate_path_handler(request: web.Request) -> web.Response:
    """Validate a path for use as Oden home directory."""
    try:
        data = await request.json()
        path = data.get("path", "")

        if not path:
            return web.json_response(
                {"valid": False, "error": "Sökväg krävs"},
                status=400,
            )

        # Normalize and perform basic safety checks on the user-provided path
        try:
            resolved_path = normalize_path(path)
        except (OSError, RuntimeError, ValueError):
            return web.json_response(
                {"valid": False, "error": "Ogiltig sökväg"},
                status=400,
            )

        # Disallow using the filesystem root as Oden home
        if is_filesystem_root(resolved_path):
            return web.json_response(
                {"valid": False, "error": "Sökvägen är inte tillåten"},
                status=400,
            )

        # Constrain the path to be within the default Oden home directory
        # (Skip this check when ODEN_HOME env var is set, e.g. Docker)
        import os

        safe_root = normalize_path(DEFAULT_ODEN_HOME)
        if not os.environ.get("ODEN_HOME") and not (
            resolved_path == safe_root or is_within_directory(resolved_path, safe_root)
        ):
            return web.json_response(
                {"valid": False, "error": "Sökvägen är inte tillåten"},
                status=400,
            )

        is_valid, error = validate_oden_home(resolved_path)

        if is_valid:
            # Check if there's already a config.db
            db_exists = (resolved_path / "config.db").exists()
            ini_exists = (resolved_path / "config.ini").exists()

            return web.json_response(
                {
                    "valid": True,
                    "path": str(resolved_path),
                    "exists": resolved_path.exists(),
                    "has_config_db": db_exists,
                    "has_config_ini": ini_exists,
                }
            )
        else:
            return web.json_response(
                {
                    "valid": False,
                    "error": error,
                    "can_reset": error == "corrupt",
                }
            )

    except json.JSONDecodeError:
        return web.json_response({"valid": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error validating path: {e}")
        return web.json_response({"valid": False, "error": str(e)}, status=500)


async def setup_reset_config_handler(request: web.Request) -> web.Response:
    """Clear pointer file to re-enter setup mode (preserves config.db)."""
    try:
        if soft_reset_config():
            return web.json_response(
                {
                    "success": True,
                    "message": "Setup startas om. Befintlig konfiguration behålls.",
                }
            )
        else:
            return web.json_response(
                {"success": False, "error": "Kunde inte återställa konfiguration"},
                status=500,
            )
    except Exception as e:
        logger.error(f"Error resetting config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


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

        # First ensure oden_home is set up (creates pointer file and initializes db)
        success, error = setup_oden_home(DEFAULT_ODEN_HOME)
        if not success:
            return web.json_response(
                {"success": False, "error": f"Kunde inte skapa konfiguration: {error}"},
                status=500,
            )

        # Read existing config from the (possibly surviving) database
        # so we preserve customized values like regex_patterns, templates, etc.
        from oden.config_db import get_all_config

        existing = {}
        if CONFIG_DB.exists():
            try:
                existing = get_all_config(CONFIG_DB)
                logger.info("Merging setup values with existing config (%d keys)", len(existing))
            except Exception as e:
                logger.warning(f"Could not read existing config for merge: {e}")

        # Setup-managed keys — only these are set during initial setup
        setup_updates = {
            "vault_path": vault_path,
            "signal_number": signal_number,
            "display_name": display_name,
        }

        # For fresh installs (no existing config), add sensible defaults
        if not existing:
            setup_updates.update(
                {
                    "append_window_minutes": 30,
                    "startup_message": "self",
                    "plus_plus_enabled": False,
                    "timezone": "Europe/Stockholm",
                    "web_enabled": True,
                    "web_port": 8080,
                }
            )

        # Merge: existing config + setup updates (setup wins)
        config_dict = {**existing, **setup_updates}

        save_config(config_dict)
        logger.info(f"Setup complete. Config saved to {CONFIG_DB}")

        return web.json_response(
            {
                "success": True,
                "message": "Konfiguration sparad! Oden startar om...",
                "config_path": str(CONFIG_DB),
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
