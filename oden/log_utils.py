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


def configure_logging() -> None:
    """Configure logging with console output, file output, and in-memory buffer.

    The log level is read from a persistent file next to the config database.
    If the file doesn't exist (first run / setup), DEBUG is used so that all
    setup activity is captured. After setup completes, the configured level
    is written to the file and applied via apply_log_level().
    """
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    from oden.config import LOG_FILE
    from oden.log_buffer import get_log_buffer

    level = read_log_level()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation (5MB max, keep 3 backups)
    if LOG_FILE:
        try:
            log_path = Path(LOG_FILE).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            root_logger.info(f"Logging to file: {log_path}")
        except Exception as e:
            root_logger.warning(f"Could not set up file logging: {e}")

    # In-memory log buffer for web GUI
    log_buffer = get_log_buffer()
    log_buffer.setLevel(level)
    root_logger.addHandler(log_buffer)

    root_logger.info(f"Logging initialized at {logging.getLevelName(level)} level")
