"""
Setup wizard handlers for Oden web GUI.

These handlers manage the first-run configuration wizard,
including Signal account linking and registration, and
config directory selection.
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
from oden import config as config_module
from oden.bundle_utils import (
    DEFAULT_ODEN_HOME,
    get_bundle_path,
    get_oden_home_path,
    validate_oden_home,
)
from oden.config import (
    DEFAULT_VAULT_PATH,
    is_configured,
    save_config,
    setup_oden_home,
    soft_reset_config,
)
from oden.config_db import get_all_config
from oden.path_utils import (
    is_filesystem_root,
    is_within_directory,
    normalize_path,
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

    # If is_configured passes, also validate the signal number against accounts.
    # Reuse any accounts already fetched above to avoid duplicate disk I/O.
    if configured:
        from oden.config import validate_signal_number

        _valid, _verr, validated_accounts = validate_signal_number(
            accounts=existing_accounts or None,
        )
        if not _valid:
            configured = False
            config_error = _verr
        # Merge discovered accounts so we never re-scan below
        if validated_accounts and not existing_accounts:
            existing_accounts = validated_accounts

    # Get current oden_home from pointer file
    current_oden_home = get_oden_home_path()

    # Check for recovery candidate: pointer file missing but config.db exists
    recovery_candidate = None
    recovery_config = None
    if config_error == "no_pointer":
        candidate_db = DEFAULT_ODEN_HOME / "config.db"
        if candidate_db.exists():
            is_valid, _db_error = validate_oden_home(DEFAULT_ODEN_HOME)
            if is_valid:
                recovery_candidate = str(DEFAULT_ODEN_HOME)
                logger.warning(
                    "Recovery candidate: pointer file missing but config.db exists at %s",
                    DEFAULT_ODEN_HOME,
                )

                # Read saved config so the UI can pre-populate fields
                try:
                    saved = get_all_config(candidate_db)
                    recovery_config = {
                        "vault_path": saved.get("vault_path", str(DEFAULT_VAULT_PATH)),
                        "signal_number": saved.get("signal_number", ""),
                        "display_name": saved.get("display_name", ""),
                        "whitelist_groups": saved.get("whitelist_groups", []),
                    }
                    logger.info(
                        "Recovery config loaded: signal_number=%s, vault_path=%s",
                        recovery_config["signal_number"],
                        recovery_config["vault_path"],
                    )
                except Exception as e:
                    logger.warning("Could not read saved config for recovery: %s", e)

    # When the configured number doesn't match any signal-cli account,
    # eagerly load accounts so the UI can show a selection immediately.
    # (validate_signal_number already populated existing_accounts above,
    # so this branch only fires if that didn't run.)
    if config_error == "invalid_account" and not existing_accounts:
        from oden.signal_manager import get_existing_accounts

        try:
            existing_accounts = get_existing_accounts()
        except Exception as e:
            logger.debug("Could not load accounts for invalid_account flow: %s", e)

    if _linker is None:
        return web.json_response(
            {
                "status": "idle",
                "configured": configured,
                "config_error": config_error,
                "oden_home": str(current_oden_home) if current_oden_home else str(DEFAULT_ODEN_HOME),
                "default_oden_home": str(DEFAULT_ODEN_HOME),
                "default_vault": str(DEFAULT_VAULT_PATH),
                "existing_accounts": existing_accounts,
                "recovery_candidate": recovery_candidate,
                "recovery_config": recovery_config,
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
    # Ensure signal-data directory exists before running signal-cli.
    # During setup mode, ensure_oden_directories() hasn't been called yet,
    # so the directory that SIGNAL_CLI_CONFIG_DIR points to may not exist.
    from oden import config as cfg
    from oden.path_utils import ensure_directory
    from oden.signal_linker import SignalLinker

    success, err = ensure_directory(cfg.SIGNAL_DATA_PATH)
    if not success:
        logger.error(
            "Failed to create SIGNAL_DATA_PATH directory '%s': %s",
            cfg.SIGNAL_DATA_PATH,
            err,
        )
        return web.json_response(
            {
                "success": False,
                "error": f"Kunde inte skapa signal-data-katalogen: {err}",
                "status": "error",
            },
            status=500,
        )

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
    """Set up the Oden home directory."""
    try:
        data = await request.json()
        oden_home_path = data.get("oden_home", str(DEFAULT_ODEN_HOME))

        # Validate and set up; primary path validation is handled inside setup_oden_home
        success, error = setup_oden_home(Path(oden_home_path))

        if success:
            logger.info("Oden home directory set to: %s", oden_home_path)

            db_path = Path(oden_home_path) / "config.db"

            # Check if configuration is now fully complete (e.g. during recovery)
            fully_configured, _config_error = is_configured()
            logger.info(
                "Oden home setup result: fully_configured=%s, config_error=%s",
                fully_configured,
                _config_error,
            )

            # Read saved config so the UI can pre-populate form fields
            saved_config = None
            if db_path.exists():
                try:
                    saved = get_all_config(db_path)
                    saved_config = {
                        "vault_path": saved.get("vault_path", str(DEFAULT_VAULT_PATH)),
                        "signal_number": saved.get("signal_number", ""),
                        "display_name": saved.get("display_name", ""),
                        "whitelist_groups": saved.get("whitelist_groups", []),
                    }
                    logger.info(
                        "Saved config returned to UI: signal_number=%s, vault_path=%s",
                        saved_config["signal_number"],
                        saved_config["vault_path"],
                    )
                except Exception as e:
                    logger.warning("Could not read saved config for recovery: %s", e)

            return web.json_response(
                {
                    "success": True,
                    "message": "Konfigurationskatalog skapad",
                    "oden_home": oden_home_path,
                    "fully_configured": fully_configured,
                    "saved_config": saved_config,
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

            return web.json_response(
                {
                    "valid": True,
                    "path": str(resolved_path),
                    "exists": resolved_path.exists(),
                    "has_config_db": db_exists,
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

        # Validate that the number exists in signal-cli accounts
        from oden.signal_manager import get_existing_accounts

        try:
            accounts = get_existing_accounts()
            account_numbers = [a["number"] for a in accounts]
            if accounts and signal_number not in account_numbers:
                logger.warning(
                    "Setup save rejected: %s not in signal-cli accounts %s",
                    signal_number,
                    account_numbers,
                )
                return web.json_response(
                    {
                        "success": False,
                        "error": f"Numret {signal_number} finns inte bland signal-cli:s konton. "
                        f"Tillgängliga konton: {', '.join(account_numbers)}",
                    },
                    status=400,
                )
        except Exception as e:
            logger.debug("Could not validate signal_number against accounts: %s", e)

        # Expand and validate vault path
        vault_path = str(Path(vault_path).expanduser())

        # Create vault directory
        Path(vault_path).mkdir(parents=True, exist_ok=True)

        # Ensure oden_home is set up (creates pointer file and initializes db).
        # Use the current oden_home from the config module if already configured
        # (e.g. set during step 1 or recovery), otherwise fall back to default.
        current_home = get_oden_home_path() or DEFAULT_ODEN_HOME
        success, error = setup_oden_home(current_home)
        if not success:
            return web.json_response(
                {"success": False, "error": f"Kunde inte skapa konfiguration: {error}"},
                status=500,
            )

        # Read existing config from the (possibly surviving) database
        # so we preserve customized values like regex_patterns, templates, etc.
        # Use the live config path (not the import-time binding which may be stale).
        from oden.config_db import get_all_config

        config_db_path = config_module.get_config_path()
        logger.info("Setup save: CONFIG_DB path = %s", config_db_path)
        existing = {}
        if config_db_path.exists():
            try:
                existing = get_all_config(config_db_path)
                logger.info(
                    "Existing config loaded for merge: %d keys, signal_number=%s",
                    len(existing),
                    existing.get("signal_number", "<missing>"),
                )
            except Exception as e:
                logger.warning(f"Could not read existing config for merge: {e}")

        # Setup-managed keys — only these are set during initial setup
        setup_updates = {
            "vault_path": vault_path,
            "signal_number": signal_number,
            "display_name": display_name,
        }
        logger.info("Setup updates to apply: %s", setup_updates)

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

        # Verify the save by reading back the signal_number
        verify = get_all_config(config_db_path)
        saved_number = verify.get("signal_number", "")
        if saved_number != signal_number:
            logger.error(
                "POST-SAVE VERIFICATION FAILED: expected signal_number=%s, got=%s (db=%s)",
                signal_number,
                saved_number,
                config_db_path,
            )
        else:
            logger.info("Setup complete. Config verified at %s (signal_number=%s)", config_db_path, saved_number)

        return web.json_response(
            {
                "success": True,
                "message": "Konfiguration sparad! Oden startar om...",
                "config_path": str(config_db_path),
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
        # Ensure signal-data directory exists (same reason as in start_link)
        from oden import config as cfg
        from oden.path_utils import ensure_directory
        from oden.signal_registrar import SignalRegistrar

        success, error = ensure_directory(cfg.SIGNAL_DATA_PATH)
        if not success:
            logger.error(
                "Failed to create signal-data directory %s: %s",
                cfg.SIGNAL_DATA_PATH,
                error,
            )
            return web.json_response(
                {
                    "success": False,
                    "error": f"Kunde inte skapa signal-data-katalogen: {error}",
                },
                status=500,
            )

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
