"""
Configuration-related handlers for Oden web GUI.
"""

import json
import logging

from aiohttp import web

from oden.config import (
    CONFIG_DB,
    DEFAULT_VAULT_PATH,
    ODEN_HOME,
    export_config_to_ini,
    get_config,
    reload_config,
    reset_config,
    save_config,
)
from oden.config_db import get_all_config

logger = logging.getLogger(__name__)


async def config_handler(request: web.Request) -> web.Response:
    """Return current config as JSON (reads live from database)."""
    # Read config fresh from database to support live reload
    config = get_config()
    config_data = {
        "signal_number": config["signal_number"],
        "display_name": config.get("display_name"),
        "signal_cli_host": config.get("signal_cli_host", "127.0.0.1"),
        "signal_cli_port": config.get("signal_cli_port", 7583),
        "signal_cli_path": config.get("signal_cli_path"),
        "signal_cli_log_file": config.get("signal_cli_log_file"),
        "unmanaged_signal_cli": config.get("unmanaged_signal_cli", False),
        "vault_path": config["vault_path"],
        "timezone": str(config["timezone"]),
        "append_window_minutes": config.get("append_window_minutes", 30),
        "startup_message": config.get("startup_message", "self"),
        "ignored_groups": config.get("ignored_groups", []),
        "whitelist_groups": config.get("whitelist_groups", []),
        "plus_plus_enabled": config.get("plus_plus_enabled", False),
        "filename_format": config.get("filename_format", "classic"),
        "regex_patterns": config.get("regex_patterns", {}),
        "log_level": logging.getLevelName(config["log_level"]),
        "web_enabled": config.get("web_enabled", True),
        "web_port": config.get("web_port", 8080),
        "web_access_log": config.get("web_access_log"),
        "oden_home": str(ODEN_HOME),
        "config_db_path": str(CONFIG_DB),
    }
    return web.json_response(config_data)


async def config_file_get_handler(request: web.Request) -> web.Response:
    """Return the configuration as INI format (for export/display)."""
    try:
        ini_content = export_config_to_ini()
        return web.json_response({"content": ini_content})
    except Exception as e:
        logger.error(f"Error exporting config to INI: {e}")
        return web.json_response({"content": "", "error": str(e)}, status=500)


async def config_export_handler(request: web.Request) -> web.Response:
    """Export configuration as downloadable INI file."""
    try:
        ini_content = export_config_to_ini()
        return web.Response(
            text=ini_content,
            content_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=oden-config.ini"},
        )
    except Exception as e:
        logger.error(f"Error exporting config: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def config_file_save_handler(request: web.Request) -> web.Response:
    """Save configuration from INI format (for import)."""
    try:
        import configparser

        from oden.config_db import migrate_from_ini

        data = await request.json()
        content = data.get("content", "")
        do_reload = data.get("reload", False)

        if not content.strip():
            return web.json_response({"success": False, "error": "Config kan inte vara tom"}, status=400)

        # Validate by trying to parse it
        config = configparser.RawConfigParser()
        try:
            config.read_string(content)
        except configparser.Error as e:
            return web.json_response({"success": False, "error": f"Ogiltig INI-syntax: {e}"}, status=400)

        # Check required sections
        if not config.has_section("Vault") or not config.has_section("Signal"):
            return web.json_response(
                {"success": False, "error": "Config måste ha [Vault] och [Signal] sektioner"},
                status=400,
            )

        # Write to temp file and migrate
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            from pathlib import Path

            success, error = migrate_from_ini(Path(temp_path), CONFIG_DB)
            if not success:
                return web.json_response({"success": False, "error": error}, status=400)
        finally:
            Path(temp_path).unlink(missing_ok=True)

        logger.info(f"Config imported from INI via web GUI (reload={do_reload})")

        # Trigger live reload if requested
        if do_reload:
            reload_config()
            logger.info("Configuration reloaded")

        return web.json_response({"success": True, "message": "Config importerad"})

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error importing config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def config_save_handler(request: web.Request) -> web.Response:
    """Save configuration from structured form data and trigger live reload.

    Merges form data with existing config to preserve fields not shown
    in the form (e.g. regex_patterns, templates, log paths).
    """
    try:
        data = await request.json()

        # Read existing config first so we only overwrite form-managed keys
        existing = get_all_config(CONFIG_DB)

        # Keys managed by the web form — update only these
        form_updates = {
            "signal_number": data.get("signal_number", ""),
            "display_name": data.get("display_name", "oden"),
            "vault_path": data.get("vault_path", str(DEFAULT_VAULT_PATH)),
            "timezone": data.get("timezone", "Europe/Stockholm"),
            "append_window_minutes": data.get("append_window_minutes", 30),
            "startup_message": data.get("startup_message", "self"),
            "plus_plus_enabled": data.get("plus_plus_enabled", False),
            "ignored_groups": data.get("ignored_groups", []),
            "whitelist_groups": data.get("whitelist_groups", []),
            "signal_cli_host": data.get("signal_cli_host", "127.0.0.1"),
            "signal_cli_port": data.get("signal_cli_port", 7583),
            "signal_cli_path": data.get("signal_cli_path"),
            "unmanaged_signal_cli": data.get("unmanaged_signal_cli", False),
            "web_enabled": data.get("web_enabled", True),
            "web_port": data.get("web_port", 8080),
            "log_level": data.get("log_level", "INFO"),
            "filename_format": data.get("filename_format", "classic"),
        }

        # Validate required fields
        if not form_updates["signal_number"] or form_updates["signal_number"] == "+46XXXXXXXXX":
            return web.json_response(
                {"success": False, "error": "Signal-nummer måste anges"},
                status=400,
            )

        # Merge: existing config + form updates (form wins)
        config_dict = {**existing, **form_updates}

        # Save config
        save_config(config_dict)
        logger.info(f"Config saved via web GUI form to {CONFIG_DB}")

        # Trigger live reload
        reload_config()
        logger.info("Configuration reloaded (live reload)")

        return web.json_response(
            {
                "success": True,
                "message": "Konfiguration sparad och applicerad!",
            }
        )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error saving config via form: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def config_reset_handler(request: web.Request) -> web.Response:
    """Reset configuration by deleting the database and pointer file."""
    try:
        if reset_config():
            return web.json_response(
                {
                    "success": True,
                    "message": "Konfiguration återställd. Starta om Oden för att köra setup igen.",
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
