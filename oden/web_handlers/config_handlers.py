"""
Configuration-related handlers for Oden web GUI.
"""

import configparser
import json
import logging

from aiohttp import web

from oden.config import (
    CONFIG_FILE,
    DEFAULT_VAULT_PATH,
    get_config,
    reload_config,
    save_config,
)

logger = logging.getLogger(__name__)


async def config_handler(request: web.Request) -> web.Response:
    """Return current config as JSON (reads live from disk)."""
    # Read config fresh from disk to support live reload
    config = get_config()
    config_data = {
        "signal_number": config["signal_number"],
        "display_name": config["display_name"],
        "signal_cli_host": config["signal_cli_host"],
        "signal_cli_port": config["signal_cli_port"],
        "signal_cli_path": config["signal_cli_path"],
        "signal_cli_log_file": config["signal_cli_log_file"],
        "unmanaged_signal_cli": config["unmanaged_signal_cli"],
        "vault_path": config["vault_path"],
        "timezone": str(config["timezone"]),
        "append_window_minutes": config["append_window_minutes"],
        "startup_message": config["startup_message"],
        "ignored_groups": config["ignored_groups"],
        "plus_plus_enabled": config["plus_plus_enabled"],
        "regex_patterns": config["regex_patterns"],
        "log_level": logging.getLevelName(config["log_level"]),
        "web_enabled": config["web_enabled"],
        "web_port": config["web_port"],
        "web_access_log": config["web_access_log"],
    }
    return web.json_response(config_data)


async def config_file_get_handler(request: web.Request) -> web.Response:
    """Return the raw content of config.ini."""
    try:
        if CONFIG_FILE.exists():
            content = CONFIG_FILE.read_text(encoding="utf-8")
        else:
            # Fallback to local config.ini
            with open("config.ini", encoding="utf-8") as f:
                content = f.read()
        return web.json_response({"content": content})
    except FileNotFoundError:
        return web.json_response({"content": "", "error": "config.ini hittades inte"}, status=404)
    except Exception as e:
        return web.json_response({"content": "", "error": str(e)}, status=500)


async def config_file_save_handler(request: web.Request) -> web.Response:
    """Save new content to config.ini and optionally trigger live reload."""
    try:
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

        # Write to file (prefer ~/.oden/config.ini)
        config_path = CONFIG_FILE if CONFIG_FILE.exists() else "config.ini"
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"config.ini updated via web GUI (reload={do_reload})")

        # Trigger live reload if requested
        if do_reload:
            reload_config()
            logger.info("Configuration reloaded")

        return web.json_response({"success": True, "message": "Config sparad"})

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def config_save_handler(request: web.Request) -> web.Response:
    """Save configuration from structured form data and trigger live reload."""
    try:
        data = await request.json()

        # Build config dict
        config_dict = {
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
        }

        # Validate required fields
        if not config_dict["signal_number"] or config_dict["signal_number"] == "+46XXXXXXXXX":
            return web.json_response(
                {"success": False, "error": "Signal-nummer måste anges"},
                status=400,
            )

        # Save config
        save_config(config_dict)
        logger.info(f"Config saved via web GUI form to {CONFIG_FILE}")

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
