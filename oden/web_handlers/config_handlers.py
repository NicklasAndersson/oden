"""
Configuration-related handlers for Oden web GUI.
"""

import logging
import re

from aiohttp import web

from oden import config as cfg
from oden.app_state import get_app_state
from oden.config import (
    DEFAULT_VAULT_PATH,
    get_config,
    reload_config,
    reset_config,
    save_config,
)
from oden.config_db import get_all_config
from oden.web_handlers._helpers import handle_errors, parse_json_body, require_writer

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
        "auto_reaction_enabled": config.get("auto_reaction_enabled", False),
        "auto_reaction_emoji": config.get("auto_reaction_emoji", "✅"),
        "auto_read_receipt_enabled": config.get("auto_read_receipt_enabled", False),
        "db_first_enabled": config.get("db_first_enabled", True),
        "raw_message_retention_days": config.get("raw_message_retention_days", 30),
        "oden_home": str(cfg.ODEN_HOME),
        "config_db_path": str(cfg.CONFIG_DB),
    }
    return web.json_response(config_data)


@handle_errors("save config")
@parse_json_body
async def config_save_handler(request: web.Request) -> web.Response:
    """Save configuration from structured form data and trigger live reload.

    Merges form data with existing config to preserve fields not shown
    in the form (e.g. templates, log paths).
    """
    data = request["json_body"]

    # Read existing config first so we only overwrite form-managed keys
    existing = get_all_config(cfg.CONFIG_DB)

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
        "auto_reaction_enabled": data.get("auto_reaction_enabled", False),
        "auto_reaction_emoji": data.get("auto_reaction_emoji", "✅"),
        "auto_read_receipt_enabled": data.get("auto_read_receipt_enabled", False),
        "db_first_enabled": data.get("db_first_enabled", True),
        "raw_message_retention_days": data.get("raw_message_retention_days", 30),
    }

    retention_days = form_updates["raw_message_retention_days"]
    if not isinstance(retention_days, int) or retention_days < 1 or retention_days > 3650:
        return web.json_response(
            {"success": False, "error": "raw_message_retention_days måste vara ett heltal mellan 1 och 3650"},
            status=400,
        )

    # Handle regex_patterns if provided
    if "regex_patterns" in data:
        patterns = data["regex_patterns"]
        if not isinstance(patterns, dict):
            return web.json_response(
                {"success": False, "error": "regex_patterns måste vara ett objekt"},
                status=400,
            )
        # Validate each pattern is a valid regex
        for name, pattern in patterns.items():
            if not isinstance(name, str) or not name.strip():
                return web.json_response(
                    {"success": False, "error": "Regex-mönsternamn får inte vara tomt"},
                    status=400,
                )
            if not isinstance(pattern, str) or not pattern.strip():
                return web.json_response(
                    {"success": False, "error": f"Regex-mönster för '{name}' får inte vara tomt"},
                    status=400,
                )
            try:
                re.compile(pattern)
            except re.error as e:
                return web.json_response(
                    {"success": False, "error": f"Ogiltigt regex-mönster '{name}': {e}"},
                    status=400,
                )
        form_updates["regex_patterns"] = patterns

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
    logger.info(f"Config saved via web GUI form to {cfg.CONFIG_DB}")

    # Trigger live reload
    reload_config()
    logger.info("Configuration reloaded (live reload)")

    return web.json_response(
        {
            "success": True,
            "message": "Konfiguration sparad och applicerad!",
        }
    )


@handle_errors("reset config")
async def config_reset_handler(request: web.Request) -> web.Response:
    """Reset configuration by deleting the database and pointer file."""
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


# --- Signal protocol configuration ---

# Keys that map from camelCase (signal-cli) to snake_case (config_db)
_SIGNAL_CONFIG_KEYS = {
    "typingIndicators": "signal_typing_indicators",
    "linkPreviews": "signal_link_previews",
    "unidentifiedDeliveryIndicators": "signal_unidentified_delivery_indicators",
}


async def signal_config_handler(request: web.Request) -> web.Response:
    """Return locally cached Signal protocol settings."""
    from oden.config_db import get_config_value

    result = {}
    for camel_key, db_key in _SIGNAL_CONFIG_KEYS.items():
        value = get_config_value(cfg.CONFIG_DB, db_key)
        result[camel_key] = value if value is not None else False
    return web.json_response(result)


@handle_errors("save signal config")
@parse_json_body
@require_writer
async def signal_config_save_handler(request: web.Request) -> web.Response:
    """Save Signal protocol settings via updateConfiguration RPC."""
    from oden.config_db import set_config_value

    data = request["json_body"]

    params: dict = {"account": get_all_config(cfg.CONFIG_DB).get("signal_number", "")}
    values_to_save: dict = {}
    for camel_key, db_key in _SIGNAL_CONFIG_KEYS.items():
        if camel_key in data:
            value = bool(data[camel_key])
            params[camel_key] = value
            values_to_save[db_key] = value

    if len(params) <= 1:
        return web.json_response({"success": False, "error": "Inga inställningar att spara"}, status=400)

    app_state = get_app_state()
    await app_state.send_jsonrpc("updateConfiguration", params=params, timeout=10.0)

    for db_key, value in values_to_save.items():
        set_config_value(cfg.CONFIG_DB, db_key, value)

    return web.json_response({"success": True, "message": "Signal-inställningar sparade"})
