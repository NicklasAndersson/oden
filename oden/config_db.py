"""
SQLite-based configuration storage for Oden.

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
    "diagnostic_mode": False,
    "unmanaged_signal_cli": False,
    "timezone": "Europe/Stockholm",
    "append_window_minutes": 30,
    "startup_message": "self",
    "ignored_groups": [],
    "whitelist_groups": [],
    "plus_plus_enabled": False,
    "filename_format": "classic",
    "log_level": "INFO",
    "log_file": None,  # Default set per-platform in config.py
    "web_enabled": True,
    "web_port": 8080,
    "web_access_log": None,
    "auto_reaction_enabled": False,
    "auto_reaction_emoji": "✅",
    "auto_read_receipt_enabled": False,
    "db_first_enabled": True,
    "enabled_pipelines": ["group_filter", "seven_s", "fors", "generic_template"],
    "pipeline_settings": {"group_filter": {"mode": "blacklist", "groups": []}},
    "raw_message_retention_days": 30,
    "signal_typing_indicators": False,
    "signal_link_previews": False,
    "signal_unidentified_delivery_indicators": False,
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
    "diagnostic_mode": "bool",
    "unmanaged_signal_cli": "bool",
    "timezone": "str",
    "append_window_minutes": "int",
    "startup_message": "str",
    "ignored_groups": "json",
    "whitelist_groups": "json",
    "plus_plus_enabled": "bool",
    "filename_format": "str",
    "log_level": "str",
    "log_file": "str",
    "web_enabled": "bool",
    "web_port": "int",
    "web_access_log": "str",
    "regex_patterns": "json",
    "report_template": "str",
    "append_template": "str",
    "auto_reaction_enabled": "bool",
    "auto_reaction_emoji": "str",
    "auto_read_receipt_enabled": "bool",
    "db_first_enabled": "bool",
    "enabled_pipelines": "json",
    "pipeline_settings": "json",
    "raw_message_retention_days": "int",
    "signal_typing_indicators": "bool",
    "signal_link_previews": "bool",
    "signal_unidentified_delivery_indicators": "bool",
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
    is_new = not db_path.exists()
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

        # Check current schema version for migrations
        current_version = 0
        try:
            cursor.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
            row = cursor.fetchone()
            if row:
                current_version = int(row[0])
        except (sqlite3.OperationalError, ValueError):
            pass

        # Migration to schema version 2: add responses table
        if current_version < 2:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keywords TEXT NOT NULL,
                    body TEXT NOT NULL
                )
            """)
            # Seed default responses if table is empty (first migration)
            cursor.execute("SELECT COUNT(*) FROM responses")
            if cursor.fetchone()[0] == 0:
                from oden.responses_db import _seed_default_responses

                _seed_default_responses(cursor)

        # Migration to schema version 3: add groups table
        if current_version < 3:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    member_count INTEGER NOT NULL DEFAULT 0,
                    is_member INTEGER NOT NULL DEFAULT 1,
                    last_seen TEXT NOT NULL DEFAULT ''
                )
            """)

        # Migration to schema version 4: add account column to groups table
        if current_version < 4:
            cursor.execute("PRAGMA table_info(groups)")
            columns = [row[1] for row in cursor.fetchall()]
            if "account" not in columns:
                cursor.execute("ALTER TABLE groups RENAME TO groups_old")
                cursor.execute("""
                    CREATE TABLE groups (
                        group_id TEXT NOT NULL,
                        account TEXT NOT NULL DEFAULT '',
                        name TEXT NOT NULL,
                        member_count INTEGER NOT NULL DEFAULT 0,
                        is_member INTEGER NOT NULL DEFAULT 1,
                        last_seen TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (group_id, account)
                    )
                """)
                # Populate account for existing groups from configured signal_number (v3's single account),
                # falling back to '' if the config entry is missing.
                cursor.execute("SELECT value FROM config WHERE key = 'signal_number'")
                row = cursor.fetchone()
                account_value = row[0] if row and row[0] is not None else ""
                cursor.execute(
                    """
                    INSERT INTO groups (group_id, account, name, member_count, is_member, last_seen)
                    SELECT group_id, ?, name, member_count, is_member, last_seen FROM groups_old
                """,
                    (account_value,),
                )
                cursor.execute("DROP TABLE groups_old")

        # Migration to schema version 5: add raw_messages, pipeline_runs, pipeline_events
        if current_version < 5:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS raw_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    envelope_raw TEXT NOT NULL,
                    source_number TEXT,
                    source_name TEXT,
                    group_id TEXT,
                    group_name TEXT,
                    message_body TEXT,
                    has_attachments INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'received',
                    status_timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_raw_messages_account_ts ON raw_messages(account, timestamp_utc DESC)"
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_messages_status ON raw_messages(status)")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    pipeline_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at TEXT,
                    completed_at TEXT,
                    output_file TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    FOREIGN KEY (message_id) REFERENCES raw_messages(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_runs_message_id ON pipeline_runs(message_id)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(pipeline_name, status)"
            )
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    details TEXT,
                    FOREIGN KEY (run_id) REFERENCES pipeline_runs(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_events_run_id ON pipeline_events(run_id)")

        # Store current schema version (never downgrade)
        latest_version = max(current_version, 5)
        cursor.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("schema_version", str(latest_version)),
        )
        conn.commit()
        if is_new:
            logger.info("Created new config database: %s", db_path)
        else:
            logger.debug("Config database schema verified: %s", db_path)
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
            deserialized = _deserialize_value(value, value_type)
            # Don't let None overwrite meaningful defaults
            if deserialized is not None:
                config[key] = deserialized

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
