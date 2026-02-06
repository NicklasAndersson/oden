"""
SQLite-based configuration storage for Oden.

Replaces the INI-file based configuration with a SQLite database.
The database is stored in ~/.oden/config.db by default.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default configuration values
DEFAULT_CONFIG = {
    "vault_path": str(Path.home() / "oden-vault"),
    "signal_number": "+46XXXXXXXXX",
    "display_name": "oden",
    "signal_cli_path": None,
    "signal_cli_host": "127.0.0.1",
    "signal_cli_port": 7583,
    "signal_cli_log_file": None,
    "unmanaged_signal_cli": False,
    "timezone": "Europe/Stockholm",
    "append_window_minutes": 30,
    "startup_message": "self",
    "ignored_groups": [],
    "whitelist_groups": [],
    "plus_plus_enabled": False,
    "filename_format": "classic",
    "log_level": "INFO",
    "web_enabled": True,
    "web_port": 8080,
    "web_access_log": None,
    "regex_patterns": {
        "registration_number": r"[A-Z,a-z]{3}[0-9]{2}[A-Z,a-z,0-9]{1}",
        "phone_number": r"(\+46|0)[1-9][0-9]{7,8}",
        "personal_number": r"[0-9]{6}[-]?[0-9]{4}",
    },
}

# Type mapping for serialization
TYPE_MAP = {
    "vault_path": "str",
    "signal_number": "str",
    "display_name": "str",
    "signal_cli_path": "str",
    "signal_cli_host": "str",
    "signal_cli_port": "int",
    "signal_cli_log_file": "str",
    "unmanaged_signal_cli": "bool",
    "timezone": "str",
    "append_window_minutes": "int",
    "startup_message": "str",
    "ignored_groups": "json",
    "whitelist_groups": "json",
    "plus_plus_enabled": "bool",
    "filename_format": "str",
    "log_level": "str",
    "web_enabled": "bool",
    "web_port": "int",
    "web_access_log": "str",
    "regex_patterns": "json",
    "report_template": "str",
    "append_template": "str",
}


def _serialize_value(value: Any, value_type: str) -> str:
    """Serialize a value for storage in SQLite."""
    if value is None:
        return ""
    if value_type == "json":
        return json.dumps(value, ensure_ascii=False)
    if value_type == "bool":
        return "true" if value else "false"
    return str(value)


def _deserialize_value(value: str, value_type: str) -> Any:
    """Deserialize a value from SQLite storage."""
    if not value:
        return None
    if value_type == "json":
        return json.loads(value)
    if value_type == "bool":
        return value.lower() in ("true", "1", "yes")
    if value_type == "int":
        return int(value)
    return value


def init_db(db_path: Path) -> None:
    """Initialize the config database with schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                type TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Store schema version
        cursor.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
        conn.commit()
    finally:
        conn.close()


def check_db_integrity(db_path: Path) -> tuple[bool, str | None]:
    """
    Check if the database file is valid and not corrupted.

    Returns:
        (True, None) if database is valid
        (False, error_message) if database is corrupted or invalid
    """
    if not db_path.exists():
        return False, "not_found"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Run SQLite integrity check
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        if result[0] != "ok":
            conn.close()
            return False, "corrupt"

        # Check that config table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='config'")
        if cursor.fetchone() is None:
            conn.close()
            return False, "invalid_schema"

        # Check that we have at least one config value
        cursor.execute("SELECT COUNT(*) FROM config")
        count = cursor.fetchone()[0]
        if count == 0:
            conn.close()
            return False, "empty"

        conn.close()
        return True, None

    except sqlite3.DatabaseError as e:
        return False, f"corrupt: {e}"
    except Exception as e:
        return False, f"error: {e}"


def get_all_config(db_path: Path) -> dict[str, Any]:
    """Read all configuration values from the database."""
    if not db_path.exists():
        return dict(DEFAULT_CONFIG)

    conn = sqlite3.connect(db_path)
    config = dict(DEFAULT_CONFIG)

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value, type FROM config")

        for key, value, value_type in cursor.fetchall():
            config[key] = _deserialize_value(value, value_type)

    except sqlite3.Error as e:
        logger.error(f"Error reading config from database: {e}")
    finally:
        conn.close()

    return config


def get_config_value(db_path: Path, key: str) -> Any:
    """Read a single configuration value from the database."""
    if not db_path.exists():
        return DEFAULT_CONFIG.get(key)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value, type FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()

        if row:
            return _deserialize_value(row[0], row[1])
        return DEFAULT_CONFIG.get(key)

    except sqlite3.Error as e:
        logger.error(f"Error reading config value '{key}': {e}")
        return DEFAULT_CONFIG.get(key)
    finally:
        conn.close()


def set_config_value(db_path: Path, key: str, value: Any) -> bool:
    """Set a single configuration value in the database."""
    if not db_path.exists():
        init_db(db_path)

    value_type = TYPE_MAP.get(key, "str")
    serialized = _serialize_value(value, value_type)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO config (key, value, type) VALUES (?, ?, ?)",
            (key, serialized, value_type),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"Error setting config value '{key}': {e}")
        return False
    finally:
        conn.close()


def save_all_config(db_path: Path, config_dict: dict[str, Any]) -> bool:
    """Save all configuration values to the database."""
    if not db_path.exists():
        init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        for key, value in config_dict.items():
            if key in ("oden_home", "signal_data_path"):
                # Skip computed values
                continue
            value_type = TYPE_MAP.get(key, "str")
            serialized = _serialize_value(value, value_type)
            cursor.execute(
                "INSERT OR REPLACE INTO config (key, value, type) VALUES (?, ?, ?)",
                (key, serialized, value_type),
            )

        conn.commit()
        logger.info(f"Saved {len(config_dict)} config values to {db_path}")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error saving config: {e}")
        return False
    finally:
        conn.close()


def delete_db(db_path: Path) -> bool:
    """Delete the config database file."""
    try:
        if db_path.exists():
            db_path.unlink()
            logger.info(f"Deleted config database: {db_path}")
        return True
    except OSError as e:
        logger.error(f"Error deleting config database: {e}")
        return False


def migrate_from_ini(ini_path: Path, db_path: Path) -> tuple[bool, str | None]:
    """
    Migrate configuration from an INI file to SQLite database.

    Args:
        ini_path: Path to the source config.ini file
        db_path: Path to the target config.db file

    Returns:
        (True, None) on success
        (False, error_message) on failure
    """
    import configparser
    import os

    # Normalize the incoming path to avoid issues with relative components
    # and ensure we only operate on a resolved file system path.
    safe_ini_path = Path(ini_path).expanduser().resolve()

    if not safe_ini_path.exists():
        return False, f"INI-fil hittades inte: {safe_ini_path}"

    try:
        config = configparser.RawConfigParser()
        config.read(safe_ini_path)

        config_dict = {}

        # Vault section
        if config.has_section("Vault"):
            vault_path = config.get("Vault", "path", fallback=str(DEFAULT_CONFIG["vault_path"]))
            config_dict["vault_path"] = os.path.expanduser(vault_path)

        # Signal section
        if config.has_section("Signal"):
            config_dict["signal_number"] = config.get("Signal", "number", fallback="+46XXXXXXXXX")
            config_dict["display_name"] = config.get("Signal", "display_name", fallback="oden")

            signal_cli_path = config.get("Signal", "signal_cli_path", fallback=None)
            if signal_cli_path:
                config_dict["signal_cli_path"] = os.path.expanduser(signal_cli_path)

            config_dict["signal_cli_host"] = config.get("Signal", "host", fallback="127.0.0.1")
            config_dict["signal_cli_port"] = config.getint("Signal", "port", fallback=7583)
            config_dict["signal_cli_log_file"] = config.get("Signal", "log_file", fallback=None)
            config_dict["unmanaged_signal_cli"] = config.getboolean("Signal", "unmanaged_signal_cli", fallback=False)

        # Regex section
        if config.has_section("Regex"):
            config_dict["regex_patterns"] = dict(config.items("Regex"))

        # Settings section
        if config.has_section("Settings"):
            config_dict["append_window_minutes"] = config.getint("Settings", "append_window_minutes", fallback=30)
            config_dict["startup_message"] = config.get("Settings", "startup_message", fallback="self").lower()
            config_dict["plus_plus_enabled"] = config.getboolean("Settings", "plus_plus_enabled", fallback=False)
            config_dict["filename_format"] = config.get("Settings", "filename_format", fallback="classic").lower()

            ignored_groups_str = config.get("Settings", "ignored_groups", fallback="")
            config_dict["ignored_groups"] = [g.strip() for g in ignored_groups_str.split(",") if g.strip()]

            whitelist_groups_str = config.get("Settings", "whitelist_groups", fallback="")
            config_dict["whitelist_groups"] = [g.strip() for g in whitelist_groups_str.split(",") if g.strip()]

        # Timezone section
        if config.has_section("Timezone"):
            config_dict["timezone"] = config.get("Timezone", "timezone", fallback="Europe/Stockholm")

        # Logging section
        if config.has_section("Logging"):
            config_dict["log_level"] = config.get("Logging", "level", fallback="INFO").upper()

        # Web section
        if config.has_section("Web"):
            config_dict["web_enabled"] = config.getboolean("Web", "enabled", fallback=True)
            config_dict["web_port"] = config.getint("Web", "port", fallback=8080)
            config_dict["web_access_log"] = config.get("Web", "access_log", fallback=None)

        # Initialize DB and save
        init_db(db_path)
        if save_all_config(db_path, config_dict):
            logger.info(f"Successfully migrated config from {ini_path} to {db_path}")
            return True, None
        else:
            return False, "Kunde inte spara konfiguration till databasen"

    except configparser.Error as e:
        return False, f"Fel vid parsning av INI-fil: {e}"
    except Exception as e:
        logger.exception(f"Error migrating from INI: {e}")
        return False, f"Oväntat fel: {e}"


def export_to_ini(db_path: Path) -> str:
    """
    Export configuration from database to INI format string.

    Returns:
        INI-formatted configuration string
    """
    config = get_all_config(db_path)

    lines = [
        "# =============================================================================",
        "# Oden Configuration File (exporterad från databas)",
        "# =============================================================================",
        "# Denna fil är en export av konfigurationen från Odens SQLite-databas.",
        "# För att använda denna fil, importera den via setup-wizarden.",
        "# =============================================================================",
        "",
        "[Vault]",
        f"path = {config.get('vault_path', '')}",
        "",
        "[Signal]",
        f"number = {config.get('signal_number', '')}",
    ]

    if config.get("display_name"):
        lines.append(f"display_name = {config['display_name']}")
    if config.get("signal_cli_path"):
        lines.append(f"signal_cli_path = {config['signal_cli_path']}")
    if config.get("signal_cli_log_file"):
        lines.append(f"log_file = {config['signal_cli_log_file']}")
    if config.get("unmanaged_signal_cli"):
        lines.append("unmanaged_signal_cli = true")
    if config.get("signal_cli_host") and config["signal_cli_host"] != "127.0.0.1":
        lines.append(f"host = {config['signal_cli_host']}")
    if config.get("signal_cli_port") and config["signal_cli_port"] != 7583:
        lines.append(f"port = {config['signal_cli_port']}")

    # Regex section
    regex_patterns = config.get("regex_patterns", {})
    if regex_patterns:
        lines.extend(["", "[Regex]"])
        for name, pattern in regex_patterns.items():
            lines.append(f"{name} = {pattern}")

    # Settings section
    lines.extend(
        [
            "",
            "[Settings]",
            f"append_window_minutes = {config.get('append_window_minutes', 30)}",
            f"startup_message = {config.get('startup_message', 'self')}",
            f"plus_plus_enabled = {str(config.get('plus_plus_enabled', False)).lower()}",
            f"filename_format = {config.get('filename_format', 'classic')}",
        ]
    )

    ignored_groups = config.get("ignored_groups", [])
    if ignored_groups:
        lines.append(f"ignored_groups = {', '.join(ignored_groups)}")

    whitelist_groups = config.get("whitelist_groups", [])
    if whitelist_groups:
        lines.append(f"whitelist_groups = {', '.join(whitelist_groups)}")

    # Timezone section
    lines.extend(
        [
            "",
            "[Timezone]",
            f"timezone = {config.get('timezone', 'Europe/Stockholm')}",
        ]
    )

    # Web section
    lines.extend(
        [
            "",
            "[Web]",
            f"enabled = {str(config.get('web_enabled', True)).lower()}",
            f"port = {config.get('web_port', 8080)}",
        ]
    )
    if config.get("web_access_log"):
        lines.append(f"access_log = {config['web_access_log']}")

    # Logging section
    log_level = config.get("log_level", "INFO")
    if log_level != "INFO":
        lines.extend(
            [
                "",
                "[Logging]",
                f"level = {log_level}",
            ]
        )

    lines.append("")  # Final newline
    return "\n".join(lines)
