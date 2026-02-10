"""
Configuration management for Oden.

Handles loading configuration from ~/.oden/config.db (SQLite) with automatic
directory creation on first run. Maintains backward compatibility with the
module-level exports pattern.
"""

import datetime
import logging
import os
import platform
import zoneinfo
from pathlib import Path

from oden.bundle_utils import (
    DEFAULT_ODEN_HOME,
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
from oden.path_utils import (
    ensure_directory,
    normalize_path,
    validate_ini_file_path,
    validate_path_within_home,
)

logger = logging.getLogger(__name__)

# Computed paths - these depend on ODEN_HOME which may not be set yet
ODEN_HOME: Path = DEFAULT_ODEN_HOME
CONFIG_DB: Path = DEFAULT_ODEN_HOME / "config.db"
DEFAULT_VAULT_PATH: Path = Path.home() / "oden-vault"
SIGNAL_DATA_PATH: Path = DEFAULT_ODEN_HOME / "signal-data"

# Legacy compatibility
CONFIG_FILE: Path = DEFAULT_ODEN_HOME / "config.ini"


def get_default_log_path() -> Path:
    """Get platform-specific default log file path."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Logs" / "Oden" / "oden.log"
    elif system == "Windows":
        return Path.home() / "AppData" / "Local" / "Oden" / "Logs" / "oden.log"
    else:
        return Path.home() / ".local" / "state" / "oden" / "oden.log"


def _update_paths(oden_home: Path) -> None:
    """Update module-level paths based on ODEN_HOME."""
    global ODEN_HOME, CONFIG_DB, SIGNAL_DATA_PATH, CONFIG_FILE
    ODEN_HOME = oden_home
    CONFIG_DB = oden_home / "config.db"
    SIGNAL_DATA_PATH = oden_home / "signal-data"
    CONFIG_FILE = oden_home / "config.ini"  # Legacy


def ensure_oden_directories() -> None:
    """Create Oden directories if they don't exist."""
    logger.debug("Ensuring Oden directories exist")
    ensure_directory(ODEN_HOME)
    ensure_directory(SIGNAL_DATA_PATH)
    ensure_directory(DEFAULT_VAULT_PATH)


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
        logger.debug("Configuration check: no pointer file found")
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
    logger.info("Saving configuration to database")
    ensure_oden_directories()
    save_all_config(CONFIG_DB, config_dict)


def get_config() -> dict:
    """
    Reads configuration from the database and returns it as a dictionary.
    Creates default config if database doesn't exist.
    """
    ensure_oden_directories()

    # Initialize DB and run migrations (safe to call on existing DB)
    if not CONFIG_DB.exists():
        init_db(CONFIG_DB)
        # Save default config
        save_all_config(CONFIG_DB, DEFAULT_CONFIG)
    else:
        # Run migrations on existing DB
        init_db(CONFIG_DB)

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
        logger.warning("Invalid timezone '%s': %s. Trying fallback...", timezone_str, e)
        try:
            timezone = zoneinfo.ZoneInfo("Europe/Stockholm")
        except Exception:
            logger.warning("tzdata not available, using UTC")
            timezone = datetime.timezone.utc
    config["timezone"] = timezone

    # Parse log level
    log_level_str = config.get("log_level", "INFO")
    try:
        log_level = getattr(logging, log_level_str.upper())
    except AttributeError:
        log_level = logging.INFO
    config["log_level"] = log_level
    config["log_level_str"] = log_level_str.upper()

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
    global PLUS_PLUS_ENABLED, FILENAME_FORMAT, SIGNAL_CLI_LOG_FILE, LOG_LEVEL, LOG_FILE
    global WEB_ENABLED, WEB_HOST, WEB_PORT, WEB_ACCESS_LOG

    logger.info("Reloading configuration from database")

    # Re-check oden_home in case it changed
    oden_home = get_oden_home_path()
    if oden_home:
        _update_paths(oden_home)

    app_config = get_config()
    VAULT_PATH = app_config["vault_path"]
    SIGNAL_NUMBER = app_config.get("signal_number") or ""
    if not SIGNAL_NUMBER or SIGNAL_NUMBER == "+46XXXXXXXXX":
        logger.warning("SIGNAL_NUMBER is not configured after reload")
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
    LOG_FILE = app_config.get("log_file") or str(get_default_log_path())
    WEB_ENABLED = app_config.get("web_enabled", True)
    WEB_HOST = os.environ.get("WEB_HOST") or app_config.get("web_host", "127.0.0.1")
    WEB_PORT = app_config.get("web_port", 8080)
    WEB_ACCESS_LOG = app_config.get("web_access_log")

    # Persist and apply the log level so it takes effect immediately
    from oden.log_utils import apply_log_level, write_log_level

    log_level_str = app_config.get("log_level_str", "INFO")
    write_log_level(log_level_str)
    apply_log_level(LOG_LEVEL)

    logger.info("Configuration reloaded successfully")
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


def soft_reset_config() -> bool:
    """
    Clear the pointer file without deleting config.db.

    This puts Oden into setup mode while preserving all existing
    configuration values. The setup wizard will merge its changes
    into the existing database instead of starting from scratch.

    Returns:
        True if successful, False otherwise.
    """
    from oden.bundle_utils import clear_oden_home_pointer

    return clear_oden_home_pointer()


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
    # Validate and normalize the path using centralized security
    default_home = normalize_path(DEFAULT_ODEN_HOME)
    resolved_path, path_error = validate_path_within_home(path, allow_path=default_home)
    if path_error:
        return False, path_error
    path = resolved_path

    # Validate the path
    is_valid, error = validate_oden_home(path)
    if not is_valid and error not in ("not_found", "empty"):
        if error == "corrupt":
            return False, "Databasen är korrupt. Radera den och försök igen."
        return False, f"Ogiltig sökväg: {error}"

    # Create directories using centralized function
    success, dir_error = ensure_directory(path)
    if not success:
        return False, f"Kunde inte skapa katalog: {dir_error}"
    success, dir_error = ensure_directory(path / "signal-data")
    if not success:
        return False, f"Kunde inte skapa signal-data katalog: {dir_error}"

    # Update paths
    _update_paths(path)

    # Set the pointer file
    if not set_oden_home_path(path):
        return False, "Kunde inte spara konfigurationssökväg"

    # Migrate from INI if requested
    db_path = path / "config.db"
    if ini_path:
        # Validate INI file path using centralized validation
        safe_ini_path, ini_error = validate_ini_file_path(ini_path, must_be_within=path)
        if ini_error:
            return False, ini_error

        success, migrate_error = migrate_from_ini(safe_ini_path, db_path)
        if not success:
            return False, migrate_error
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
    SIGNAL_NUMBER = app_config.get("signal_number") or ""
    if not SIGNAL_NUMBER or SIGNAL_NUMBER == "+46XXXXXXXXX":
        logger.debug("SIGNAL_NUMBER not yet configured")
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
    LOG_FILE = app_config.get("log_file") or str(get_default_log_path())
    WEB_ENABLED = app_config.get("web_enabled", True)
    WEB_HOST = os.environ.get("WEB_HOST") or app_config.get("web_host", "127.0.0.1")
    WEB_PORT = app_config.get("web_port", 8080)
    WEB_ACCESS_LOG = app_config.get("web_access_log")

except Exception as e:
    logger.error("Error loading configuration: %s", e)
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
    LOG_FILE = str(get_default_log_path())
    WEB_ENABLED = True
    WEB_HOST = os.environ.get("WEB_HOST", "127.0.0.1")
    WEB_PORT = 8080
    WEB_ACCESS_LOG = None
