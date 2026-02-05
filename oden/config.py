"""
Configuration management for Oden.

Handles loading configuration from ~/.oden/config.db (SQLite) with automatic
directory creation on first run. Maintains backward compatibility with the
module-level exports pattern.
"""

import datetime
import logging
import os
import sys
import zoneinfo
from pathlib import Path

from oden.bundle_utils import (
    DEFAULT_ODEN_HOME,
    get_bundle_path,
    get_oden_home_path,
    set_oden_home_path,
    validate_oden_home,
)
from oden.config_db import (
    DEFAULT_CONFIG,
    check_db_integrity,
    delete_db,
    export_to_ini,
    get_all_config,
    init_db,
    migrate_from_ini,
    save_all_config,
)

# Computed paths - these depend on ODEN_HOME which may not be set yet
ODEN_HOME: Path = DEFAULT_ODEN_HOME
CONFIG_DB: Path = DEFAULT_ODEN_HOME / "config.db"
DEFAULT_VAULT_PATH: Path = Path.home() / "oden-vault"
SIGNAL_DATA_PATH: Path = DEFAULT_ODEN_HOME / "signal-data"

# Legacy compatibility
CONFIG_FILE: Path = DEFAULT_ODEN_HOME / "config.ini"


def _update_paths(oden_home: Path) -> None:
    """Update module-level paths based on ODEN_HOME."""
    global ODEN_HOME, CONFIG_DB, SIGNAL_DATA_PATH, CONFIG_FILE
    ODEN_HOME = oden_home
    CONFIG_DB = oden_home / "config.db"
    SIGNAL_DATA_PATH = oden_home / "signal-data"
    CONFIG_FILE = oden_home / "config.ini"  # Legacy


def get_config_template_path() -> Path:
    """Get path to config.ini.template (for migration reference)."""
    bundle_path = get_bundle_path()
    template_path = bundle_path / "config.ini.template"
    if template_path.exists():
        return template_path
    config_ini = bundle_path / "config.ini"
    if config_ini.exists():
        return config_ini
    return template_path


def ensure_oden_directories() -> None:
    """Create Oden directories if they don't exist."""
    ODEN_HOME.mkdir(parents=True, exist_ok=True)
    SIGNAL_DATA_PATH.mkdir(parents=True, exist_ok=True)
    DEFAULT_VAULT_PATH.mkdir(parents=True, exist_ok=True)


def is_configured() -> tuple[bool, str | None]:
    """
    Check if Oden has been configured.

    Returns:
        (True, None) if configured and ready
        (False, reason) if not configured:
            - "no_pointer": No oden_home pointer file exists
            - "no_db": Database file doesn't exist
            - "corrupt": Database is corrupted
            - "invalid_schema": Database has wrong schema
            - "no_signal_number": Signal number not configured
    """
    # Check if pointer file exists and points to valid directory
    oden_home = get_oden_home_path()
    if oden_home is None:
        return False, "no_pointer"

    # Update paths based on actual oden_home
    _update_paths(oden_home)

    # Check database exists and is valid
    if not CONFIG_DB.exists():
        return False, "no_db"

    is_valid, error = check_db_integrity(CONFIG_DB)
    if not is_valid:
        return False, error

    # Check if Signal number is configured
    config = get_all_config(CONFIG_DB)
    number = config.get("signal_number", "")
    if not number or number == "+46XXXXXXXXX" or number.startswith("+46XXXX"):
        return False, "no_signal_number"

    return True, None


def get_config_path() -> Path:
    """Get the path to the config database."""
    return CONFIG_DB


def save_config(config_dict: dict) -> None:
    """Save configuration to the database."""
    ensure_oden_directories()
    save_all_config(CONFIG_DB, config_dict)


def get_config() -> dict:
    """
    Reads configuration from the database and returns it as a dictionary.
    Creates default config if database doesn't exist.
    """
    ensure_oden_directories()

    # Initialize DB if not exists
    if not CONFIG_DB.exists():
        init_db(CONFIG_DB)
        # Save default config
        save_all_config(CONFIG_DB, DEFAULT_CONFIG)

    config = get_all_config(CONFIG_DB)

    # Check for signal-cli path from environment variable or .signal_cli_path file
    signal_cli_path = config.get("signal_cli_path")
    if not signal_cli_path:
        signal_cli_path = os.environ.get("SIGNAL_CLI_PATH")
    if not signal_cli_path:
        signal_cli_path_file = ODEN_HOME / ".signal_cli_path"
        if signal_cli_path_file.exists():
            signal_cli_path = signal_cli_path_file.read_text().strip()
    config["signal_cli_path"] = signal_cli_path

    # Parse timezone
    timezone_str = config.get("timezone", "Europe/Stockholm")
    try:
        timezone = zoneinfo.ZoneInfo(timezone_str)
    except Exception as e:
        print(f"Warning: Invalid timezone '{timezone_str}': {e}. Trying fallback...", file=sys.stderr)
        try:
            timezone = zoneinfo.ZoneInfo("Europe/Stockholm")
        except Exception:
            print("Warning: tzdata not available, using UTC", file=sys.stderr)
            timezone = datetime.timezone.utc
    config["timezone"] = timezone

    # Parse log level
    log_level_str = config.get("log_level", "INFO")
    try:
        log_level = getattr(logging, log_level_str.upper())
    except AttributeError:
        log_level = logging.INFO
    config["log_level"] = log_level

    # Expand user path for vault_path
    vault_path = config.get("vault_path", str(DEFAULT_VAULT_PATH))
    config["vault_path"] = os.path.expanduser(vault_path)

    # Expand signal_cli_path if set
    if config.get("signal_cli_path"):
        config["signal_cli_path"] = os.path.expanduser(config["signal_cli_path"])

    # Add computed paths
    config["oden_home"] = str(ODEN_HOME)
    config["signal_data_path"] = str(SIGNAL_DATA_PATH)

    return config


def reload_config() -> dict:
    """Reload configuration from database and update module-level variables."""
    global app_config, VAULT_PATH, SIGNAL_NUMBER, DISPLAY_NAME, SIGNAL_CLI_PATH
    global UNMANAGED_SIGNAL_CLI, SIGNAL_CLI_HOST, SIGNAL_CLI_PORT, REGEX_PATTERNS
    global TIMEZONE, APPEND_WINDOW_MINUTES, IGNORED_GROUPS, WHITELIST_GROUPS, STARTUP_MESSAGE
    global PLUS_PLUS_ENABLED, FILENAME_FORMAT, SIGNAL_CLI_LOG_FILE, LOG_LEVEL
    global WEB_ENABLED, WEB_PORT, WEB_ACCESS_LOG

    # Re-check oden_home in case it changed
    oden_home = get_oden_home_path()
    if oden_home:
        _update_paths(oden_home)

    app_config = get_config()
    VAULT_PATH = app_config["vault_path"]
    SIGNAL_NUMBER = app_config["signal_number"]
    DISPLAY_NAME = app_config.get("display_name")
    SIGNAL_CLI_PATH = app_config.get("signal_cli_path")
    UNMANAGED_SIGNAL_CLI = app_config.get("unmanaged_signal_cli", False)
    SIGNAL_CLI_HOST = app_config.get("signal_cli_host", "127.0.0.1")
    SIGNAL_CLI_PORT = app_config.get("signal_cli_port", 7583)
    REGEX_PATTERNS = app_config.get("regex_patterns", {})
    TIMEZONE = app_config["timezone"]
    APPEND_WINDOW_MINUTES = app_config.get("append_window_minutes", 30)
    IGNORED_GROUPS = app_config.get("ignored_groups", [])
    WHITELIST_GROUPS = app_config.get("whitelist_groups", [])
    STARTUP_MESSAGE = app_config.get("startup_message", "self")
    PLUS_PLUS_ENABLED = app_config.get("plus_plus_enabled", False)
    FILENAME_FORMAT = app_config.get("filename_format", "classic")
    SIGNAL_CLI_LOG_FILE = app_config.get("signal_cli_log_file")
    LOG_LEVEL = app_config["log_level"]
    WEB_ENABLED = app_config.get("web_enabled", True)
    WEB_PORT = app_config.get("web_port", 8080)
    WEB_ACCESS_LOG = app_config.get("web_access_log")

    return app_config


def export_config_to_ini() -> str:
    """Export current configuration to INI format string."""
    return export_to_ini(CONFIG_DB)


def reset_config() -> bool:
    """
    Reset configuration by deleting the database and clearing the pointer file.

    Returns:
        True if successful, False otherwise.
    """
    from oden.bundle_utils import clear_oden_home_pointer

    success = True
    if CONFIG_DB.exists() and not delete_db(CONFIG_DB):
        success = False
    if not clear_oden_home_pointer():
        success = False

    return success


def setup_oden_home(path: Path, ini_path: Path | None = None) -> tuple[bool, str | None]:
    """
    Set up the Oden home directory.

    Creates the directory, initializes the database, and optionally migrates
    from an existing INI file.

    Args:
        path: Path to use as Oden home directory
        ini_path: Optional path to config.ini to migrate from

    Returns:
        (True, None) on success
        (False, error_message) on failure
    """
    # Normalize and constrain the path selected by the user
    path = Path(path).expanduser().resolve()

    # Only allow Oden home directories under the current user's home directory,
    # unless the path is exactly the compiled-in default.
    try:
        user_home = Path.home().resolve()
        default_home = DEFAULT_ODEN_HOME.expanduser().resolve()
        if path != default_home:
            # Raises ValueError if `path` is not within `user_home`
            path.relative_to(user_home)
    except (OSError, RuntimeError):
        # If we cannot determine a safe home directory, reject the path
        return False, "Ogiltig sökväg: kunde inte verifiera hemkatalog"
    except ValueError:
        # Path is outside the allowed root
        return False, f"Ogiltig sökväg: {path}"

    # Validate the path
    is_valid, error = validate_oden_home(path)
    if not is_valid and error not in ("not_found", "empty"):
        if error == "corrupt":
            return False, "Databasen är korrupt. Radera den och försök igen."
        return False, f"Ogiltig sökväg: {error}"

    # Create directories
    try:
        path.mkdir(parents=True, exist_ok=True)
        (path / "signal-data").mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"Kunde inte skapa katalog: {e}"

    # Update paths
    _update_paths(path)

    # Set the pointer file
    if not set_oden_home_path(path):
        return False, "Kunde inte spara konfigurationssökväg"

    # Migrate from INI if requested
    db_path = path / "config.db"
    if ini_path:
        # Normalize and constrain the INI path to be within the chosen Oden home.
        try:
            raw_ini_path = Path(ini_path)
            # Resolve against the Oden home directory to prevent directory traversal
            # and disallow absolute paths outside of `path`.
            safe_ini_path = (path / raw_ini_path).resolve()
            # Raises ValueError if `safe_ini_path` is not within `path`
            safe_ini_path.relative_to(path)
        except (OSError, RuntimeError):
            return False, "Ogiltig sökväg för INI-fil: kunde inte verifiera sökväg"
        except ValueError:
            return False, f"Ogiltig sökväg för INI-fil: {ini_path}"

        # Further restrict to a specific INI file name within the validated root.
        # This prevents arbitrary file selection even inside the Oden home.
        if safe_ini_path.name != "config.ini":
            return False, f"Ogiltigt filnamn för INI-fil: {safe_ini_path.name}"

        if not safe_ini_path.exists() or not safe_ini_path.is_file():
            return False, f"INI-fil hittades inte: {safe_ini_path}"

        success, error = migrate_from_ini(safe_ini_path, db_path)
        if not success:
            return False, error
    else:
        # Initialize empty database
        init_db(db_path)

    return True, None


# Initialize paths from pointer file if it exists
_oden_home = get_oden_home_path()
if _oden_home:
    _update_paths(_oden_home)

# Load configuration on import
# This will use defaults if not configured yet
try:
    # Check if we're actually configured
    _is_configured, _config_error = is_configured()

    if _is_configured:
        app_config = get_config()
    else:
        # Use defaults but still set up the variables
        app_config = dict(DEFAULT_CONFIG)
        # Parse timezone
        try:
            app_config["timezone"] = zoneinfo.ZoneInfo("Europe/Stockholm")
        except Exception:
            app_config["timezone"] = datetime.timezone.utc
        app_config["log_level"] = logging.INFO
        app_config["oden_home"] = str(ODEN_HOME)
        app_config["signal_data_path"] = str(SIGNAL_DATA_PATH)

    # Export module-level variables
    VAULT_PATH = app_config.get("vault_path", str(DEFAULT_VAULT_PATH))
    SIGNAL_NUMBER = app_config.get("signal_number", "+46XXXXXXXXX")
    DISPLAY_NAME = app_config.get("display_name")
    SIGNAL_CLI_PATH = app_config.get("signal_cli_path")
    UNMANAGED_SIGNAL_CLI = app_config.get("unmanaged_signal_cli", False)
    SIGNAL_CLI_HOST = app_config.get("signal_cli_host", "127.0.0.1")
    SIGNAL_CLI_PORT = app_config.get("signal_cli_port", 7583)
    REGEX_PATTERNS = app_config.get("regex_patterns", {})
    TIMEZONE = app_config.get("timezone")
    APPEND_WINDOW_MINUTES = app_config.get("append_window_minutes", 30)
    IGNORED_GROUPS = app_config.get("ignored_groups", [])
    WHITELIST_GROUPS = app_config.get("whitelist_groups", [])
    STARTUP_MESSAGE = app_config.get("startup_message", "self")
    PLUS_PLUS_ENABLED = app_config.get("plus_plus_enabled", False)
    FILENAME_FORMAT = app_config.get("filename_format", "classic")
    SIGNAL_CLI_LOG_FILE = app_config.get("signal_cli_log_file")
    LOG_LEVEL = app_config.get("log_level", logging.INFO)
    WEB_ENABLED = app_config.get("web_enabled", True)
    WEB_PORT = app_config.get("web_port", 8080)
    WEB_ACCESS_LOG = app_config.get("web_access_log")

except Exception as e:
    print(f"Error loading configuration: {e}")
    # Don't exit - let the web server show setup wizard
    app_config = {}
    VAULT_PATH = str(DEFAULT_VAULT_PATH)
    SIGNAL_NUMBER = "+46XXXXXXXXX"
    DISPLAY_NAME = None
    SIGNAL_CLI_PATH = None
    UNMANAGED_SIGNAL_CLI = False
    SIGNAL_CLI_HOST = "127.0.0.1"
    SIGNAL_CLI_PORT = 7583
    REGEX_PATTERNS = {}
    TIMEZONE = datetime.timezone.utc
    APPEND_WINDOW_MINUTES = 30
    IGNORED_GROUPS = []
    WHITELIST_GROUPS = []
    STARTUP_MESSAGE = "self"
    PLUS_PLUS_ENABLED = False
    FILENAME_FORMAT = "classic"
    SIGNAL_CLI_LOG_FILE = None
    LOG_LEVEL = logging.INFO
    WEB_ENABLED = True
    WEB_PORT = 8080
    WEB_ACCESS_LOG = None
