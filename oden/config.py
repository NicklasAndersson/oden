"""
Configuration management for Oden.

Handles loading configuration from ~/.oden/config.ini with automatic
directory creation and template copying on first run.
"""

import configparser
import logging
import os
import shutil
import sys
import zoneinfo
from pathlib import Path

# Default paths
ODEN_HOME = Path.home() / ".oden"
CONFIG_FILE = ODEN_HOME / "config.ini"
DEFAULT_VAULT_PATH = Path.home() / "oden-vault"
SIGNAL_DATA_PATH = ODEN_HOME / "signal-data"


def get_bundle_path() -> Path:
    """Get the path to bundled resources (for PyInstaller builds)."""
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle
        return Path(sys._MEIPASS)
    else:
        # Running from source
        return Path(__file__).parent.parent


def get_config_template_path() -> Path:
    """Get path to config.ini.template."""
    bundle_path = get_bundle_path()
    # Check for template in bundle
    template_path = bundle_path / "config.ini.template"
    if template_path.exists():
        return template_path
    # Fallback to config.ini in project root (for development)
    config_ini = bundle_path / "config.ini"
    if config_ini.exists():
        return config_ini
    return template_path


def ensure_oden_directories() -> None:
    """Create ~/.oden and ~/oden-vault directories if they don't exist."""
    ODEN_HOME.mkdir(parents=True, exist_ok=True)
    SIGNAL_DATA_PATH.mkdir(parents=True, exist_ok=True)
    DEFAULT_VAULT_PATH.mkdir(parents=True, exist_ok=True)


def is_configured() -> bool:
    """Check if Oden has been configured (config exists with valid Signal number)."""
    if not CONFIG_FILE.exists():
        return False

    try:
        config = configparser.RawConfigParser()
        config.read(CONFIG_FILE)

        if not config.has_section("Signal"):
            return False

        number = config.get("Signal", "number", fallback="")
        # Check if number is set and not placeholder
        return bool(number and number != "+46XXXXXXXXX" and not number.startswith("+46XXXX"))
    except Exception:
        return False


def create_default_config() -> None:
    """Create a default config.ini from template."""
    ensure_oden_directories()

    if CONFIG_FILE.exists():
        return

    template_path = get_config_template_path()

    if template_path.exists():
        shutil.copy(template_path, CONFIG_FILE)
    else:
        # Create minimal config if no template found
        config_content = f"""# =============================================================================
# Oden Configuration File
# =============================================================================
# Denna fil konfigurerar Oden - Signal-till-Obsidian-bryggan.
# =============================================================================

[Vault]
path = {DEFAULT_VAULT_PATH}

[Signal]
number = +46XXXXXXXXX
display_name = oden

[Settings]
append_window_minutes = 30
startup_message = self
plus_plus_enabled = false

[Timezone]
timezone = Europe/Stockholm

[Web]
enabled = true
port = 8080
"""
        CONFIG_FILE.write_text(config_content)


def get_config_path() -> Path:
    """Get the path to the config file."""
    return CONFIG_FILE


def save_config(config_dict: dict) -> None:
    """Save configuration to config.ini."""
    ensure_oden_directories()

    config = configparser.RawConfigParser()

    # Vault section
    config.add_section("Vault")
    config.set("Vault", "path", config_dict.get("vault_path", str(DEFAULT_VAULT_PATH)))

    # Signal section
    config.add_section("Signal")
    config.set("Signal", "number", config_dict.get("signal_number", "+46XXXXXXXXX"))
    if config_dict.get("display_name"):
        config.set("Signal", "display_name", config_dict["display_name"])
    if config_dict.get("signal_cli_path"):
        config.set("Signal", "signal_cli_path", config_dict["signal_cli_path"])
    if config_dict.get("signal_cli_host") and config_dict["signal_cli_host"] != "127.0.0.1":
        config.set("Signal", "host", config_dict["signal_cli_host"])
    if config_dict.get("signal_cli_port") and config_dict["signal_cli_port"] != 7583:
        config.set("Signal", "port", str(config_dict["signal_cli_port"]))
    if config_dict.get("unmanaged_signal_cli"):
        config.set("Signal", "unmanaged_signal_cli", "true")

    # Settings section
    config.add_section("Settings")
    config.set("Settings", "append_window_minutes", str(config_dict.get("append_window_minutes", 30)))
    config.set("Settings", "startup_message", config_dict.get("startup_message", "self"))
    config.set("Settings", "plus_plus_enabled", str(config_dict.get("plus_plus_enabled", False)).lower())
    ignored_groups = config_dict.get("ignored_groups", [])
    if ignored_groups:
        if isinstance(ignored_groups, list):
            config.set("Settings", "ignored_groups", ", ".join(ignored_groups))
        else:
            config.set("Settings", "ignored_groups", ignored_groups)

    # Timezone section
    config.add_section("Timezone")
    config.set("Timezone", "timezone", config_dict.get("timezone", "Europe/Stockholm"))

    # Logging section
    if config_dict.get("log_level") and config_dict["log_level"] != "INFO":
        config.add_section("Logging")
        config.set("Logging", "level", config_dict["log_level"])

    # Web section
    config.add_section("Web")
    config.set("Web", "enabled", str(config_dict.get("web_enabled", True)).lower())
    config.set("Web", "port", str(config_dict.get("web_port", 8080)))

    with open(CONFIG_FILE, "w") as f:
        config.write(f)


def get_config() -> dict:
    """
    Reads configuration from ~/.oden/config.ini and returns it as a dictionary.
    Creates default config if it doesn't exist.
    """
    ensure_oden_directories()

    # Create default config if not exists
    if not CONFIG_FILE.exists():
        create_default_config()

    # Use RawConfigParser to avoid interpolation issues with regex patterns
    config = configparser.RawConfigParser()
    config.read(CONFIG_FILE)

    # Basic error handling - create sections if missing
    if not config.has_section("Vault"):
        config.add_section("Vault")
        config.set("Vault", "path", str(DEFAULT_VAULT_PATH))

    if not config.has_section("Signal"):
        config.add_section("Signal")
        config.set("Signal", "number", "+46XXXXXXXXX")

    # Read values
    vault_path = config.get("Vault", "path", fallback=str(DEFAULT_VAULT_PATH))
    signal_number = config.get("Signal", "number", fallback="+46XXXXXXXXX")
    display_name = config.get("Signal", "display_name", fallback=None)
    signal_cli_path = config.get("Signal", "signal_cli_path", fallback=None)
    unmanaged_signal_cli = config.getboolean("Signal", "unmanaged_signal_cli", fallback=False)
    signal_cli_host = config.get("Signal", "host", fallback="127.0.0.1")
    signal_cli_port = config.getint("Signal", "port", fallback=7583)
    signal_cli_log_file = config.get("Signal", "log_file", fallback=None)

    # Read regex patterns if available
    regex_patterns = {}
    if config.has_section("Regex"):
        regex_patterns = dict(config.items("Regex"))

    # Read settings if available
    append_window_minutes = 30
    ignored_groups = []
    startup_message = "self"
    plus_plus_enabled = False
    if config.has_section("Settings"):
        append_window_minutes = config.getint("Settings", "append_window_minutes", fallback=30)
        ignored_groups_str = config.get("Settings", "ignored_groups", fallback="")
        ignored_groups = [group.strip() for group in ignored_groups_str.split(",") if group.strip()]
        startup_message = config.get("Settings", "startup_message", fallback="self").lower()
        if startup_message not in ("self", "all", "off"):
            print(f"Warning: Invalid startup_message '{startup_message}'. Using 'self'", file=sys.stderr)
            startup_message = "self"
        plus_plus_enabled = config.getboolean("Settings", "plus_plus_enabled", fallback=False)

    # Read timezone if available, defaults to Europe/Stockholm
    timezone_str = "Europe/Stockholm"
    if config.has_section("Timezone"):
        timezone_str = config.get("Timezone", "timezone", fallback="Europe/Stockholm")

    try:
        timezone = zoneinfo.ZoneInfo(timezone_str)
    except Exception as e:
        print(f"Warning: Invalid timezone '{timezone_str}': {e}. Using Europe/Stockholm", file=sys.stderr)
        timezone = zoneinfo.ZoneInfo("Europe/Stockholm")

    # Read logging level if available, defaults to INFO
    log_level_str = config.get("Logging", "level", fallback="INFO")
    try:
        log_level = getattr(logging, log_level_str.upper())
    except AttributeError:
        log_level = logging.INFO

    # Read web server settings if available
    web_enabled = True
    web_port = 8080
    web_access_log = None
    if config.has_section("Web"):
        web_enabled = config.getboolean("Web", "enabled", fallback=True)
        web_port = config.getint("Web", "port", fallback=8080)
        web_access_log = config.get("Web", "access_log", fallback=None)

    # Expand user path for vault_path
    return {
        "vault_path": os.path.expanduser(vault_path),
        "signal_number": signal_number,
        "display_name": display_name,
        "signal_cli_path": os.path.expanduser(signal_cli_path) if signal_cli_path else None,
        "unmanaged_signal_cli": unmanaged_signal_cli,
        "signal_cli_host": signal_cli_host,
        "signal_cli_port": signal_cli_port,
        "regex_patterns": regex_patterns,
        "timezone": timezone,
        "append_window_minutes": append_window_minutes,
        "ignored_groups": ignored_groups,
        "startup_message": startup_message,
        "plus_plus_enabled": plus_plus_enabled,
        "signal_cli_log_file": signal_cli_log_file,
        "log_level": log_level,
        "web_enabled": web_enabled,
        "web_port": web_port,
        "web_access_log": web_access_log,
        "oden_home": str(ODEN_HOME),
        "signal_data_path": str(SIGNAL_DATA_PATH),
    }


def reload_config() -> dict:
    """Reload configuration from disk and update module-level variables."""
    global app_config, VAULT_PATH, SIGNAL_NUMBER, DISPLAY_NAME, SIGNAL_CLI_PATH
    global UNMANAGED_SIGNAL_CLI, SIGNAL_CLI_HOST, SIGNAL_CLI_PORT, REGEX_PATTERNS
    global TIMEZONE, APPEND_WINDOW_MINUTES, IGNORED_GROUPS, STARTUP_MESSAGE
    global PLUS_PLUS_ENABLED, SIGNAL_CLI_LOG_FILE, LOG_LEVEL, WEB_ENABLED, WEB_PORT, WEB_ACCESS_LOG

    app_config = get_config()
    VAULT_PATH = app_config["vault_path"]
    SIGNAL_NUMBER = app_config["signal_number"]
    DISPLAY_NAME = app_config["display_name"]
    SIGNAL_CLI_PATH = app_config["signal_cli_path"]
    UNMANAGED_SIGNAL_CLI = app_config["unmanaged_signal_cli"]
    SIGNAL_CLI_HOST = app_config["signal_cli_host"]
    SIGNAL_CLI_PORT = app_config["signal_cli_port"]
    REGEX_PATTERNS = app_config["regex_patterns"]
    TIMEZONE = app_config["timezone"]
    APPEND_WINDOW_MINUTES = app_config["append_window_minutes"]
    IGNORED_GROUPS = app_config["ignored_groups"]
    STARTUP_MESSAGE = app_config["startup_message"]
    PLUS_PLUS_ENABLED = app_config["plus_plus_enabled"]
    SIGNAL_CLI_LOG_FILE = app_config["signal_cli_log_file"]
    LOG_LEVEL = app_config["log_level"]
    WEB_ENABLED = app_config["web_enabled"]
    WEB_PORT = app_config["web_port"]
    WEB_ACCESS_LOG = app_config["web_access_log"]

    return app_config


# Load configuration on import
try:
    app_config = get_config()
    VAULT_PATH = app_config["vault_path"]
    SIGNAL_NUMBER = app_config["signal_number"]
    DISPLAY_NAME = app_config["display_name"]
    SIGNAL_CLI_PATH = app_config["signal_cli_path"]
    UNMANAGED_SIGNAL_CLI = app_config["unmanaged_signal_cli"]
    SIGNAL_CLI_HOST = app_config["signal_cli_host"]
    SIGNAL_CLI_PORT = app_config["signal_cli_port"]
    REGEX_PATTERNS = app_config["regex_patterns"]
    TIMEZONE = app_config["timezone"]
    APPEND_WINDOW_MINUTES = app_config["append_window_minutes"]
    IGNORED_GROUPS = app_config["ignored_groups"]
    STARTUP_MESSAGE = app_config["startup_message"]
    PLUS_PLUS_ENABLED = app_config["plus_plus_enabled"]
    SIGNAL_CLI_LOG_FILE = app_config["signal_cli_log_file"]
    LOG_LEVEL = app_config["log_level"]
    WEB_ENABLED = app_config["web_enabled"]
    WEB_PORT = app_config["web_port"]
    WEB_ACCESS_LOG = app_config["web_access_log"]
except Exception as e:
    print(f"Error loading configuration: {e}")
    sys.exit(1)
