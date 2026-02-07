"""
Logging utilities for Oden.

Provides centralized log level management with file-based persistence.
The log level is stored in a plain-text file next to the config database.
If the file is missing (e.g. during first-run setup), DEBUG is used to
ensure verbose logging during initial configuration.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Level file name, stored next to config.db in ODEN_HOME
_LOG_LEVEL_FILENAME = "log_level"


def get_log_level_path() -> Path:
    """Get the path to the log level file.

    Returns:
        Path to the log_level file inside ODEN_HOME.
    """
    from oden.config import ODEN_HOME

    return ODEN_HOME / _LOG_LEVEL_FILENAME


def read_log_level() -> int:
    """Read the persisted log level from disk.

    Returns:
        The logging level as an integer constant (e.g. logging.INFO).
        Returns logging.DEBUG if the file is missing or unreadable,
        ensuring verbose output during first-run setup.
    """
    path = get_log_level_path()
    try:
        if path.exists():
            level_str = path.read_text(encoding="utf-8").strip().upper()
            level = getattr(logging, level_str, None)
            if isinstance(level, int):
                return level
            logger.warning(
                "Invalid log level '%s' in %s, falling back to DEBUG",
                level_str,
                path,
            )
    except Exception as e:
        logger.debug("Could not read log level file %s: %s", path, e)

    # No file or unreadable → DEBUG (verbose during setup)
    return logging.DEBUG


def write_log_level(level_str: str) -> None:
    """Write the log level string to disk.

    Args:
        level_str: Log level name (e.g. "INFO", "DEBUG").
    """
    path = get_log_level_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(level_str.strip().upper() + "\n", encoding="utf-8")
        logger.debug("Wrote log level '%s' to %s", level_str, path)
    except Exception as e:
        logger.warning("Could not write log level file %s: %s", path, e)


def apply_log_level(level: int) -> None:
    """Apply a log level to the root logger and all its handlers.

    Args:
        level: Logging level constant (e.g. logging.INFO).
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)
    logger.info("Log level set to %s", logging.getLevelName(level))
