"""
Utility functions for handling PyInstaller bundles and bundled resources.

This module provides functions for detecting if the application is running
as a PyInstaller bundle and accessing bundled resources. Also handles the
oden_home pointer file for locating the config directory.
"""

import logging
import platform
import sys
from pathlib import Path

from oden.path_utils import ensure_directory, normalize_path

logger = logging.getLogger(__name__)

# Default paths
DEFAULT_ODEN_HOME = Path.home() / ".oden"
POINTER_FILENAME = "oden_home.txt"


def get_bundle_path() -> Path:
    """Get the path to bundled resources (for PyInstaller builds).

    Returns:
        Path to the bundle directory (_MEIPASS for frozen apps,
        or project root when running from source).
    """
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle
        return Path(sys._MEIPASS)
    else:
        # Running from source
        return Path(__file__).parent.parent


def is_bundled() -> bool:
    """Check if running as a PyInstaller bundle.

    Returns:
        True if running as a frozen bundle, False otherwise.
    """
    return getattr(sys, "frozen", False)


def get_bundled_java_path() -> str | None:
    """Get path to bundled JRE based on platform and architecture.

    Returns:
        Path to the java executable if bundled JRE exists, None otherwise.
    """
    if not is_bundled():
        return None

    bundle_path = get_bundle_path()
    system = platform.system()
    arch = platform.machine()

    # On macOS, we always bundle x64 JRE (works via Rosetta on Apple Silicon)
    if system == "Darwin":
        jre_dir = "jre-x64"
    # On Windows/Linux, match the architecture
    elif arch == "arm64":
        jre_dir = "jre-arm64"
    elif arch in ("x86_64", "AMD64"):
        jre_dir = "jre-x64"
    else:
        logger.warning(f"Unknown architecture: {arch}")
        return None

    java_path = bundle_path / jre_dir / "bin" / "java"
    if java_path.exists():
        return str(java_path)
    else:
        logger.warning(f"Bundled Java not found at {java_path}")
        return None


def get_app_support_dir() -> Path:
    """Get the application support directory for storing the pointer file.

    On macOS: ~/Library/Application Support/Oden
    On Linux: ~/.local/share/oden
    On Windows: %APPDATA%/Oden

    Returns:
        Path to the application support directory.
    """
    system = platform.system()

    if system == "Darwin":
        app_support = Path.home() / "Library" / "Application Support" / "Oden"
    elif system == "Windows":
        app_data = Path.home() / "AppData" / "Roaming" / "Oden"
        app_support = app_data
    else:
        # Linux and other Unix-like systems
        app_support = Path.home() / ".local" / "share" / "oden"

    return app_support


def get_pointer_file_path() -> Path:
    """Get the path to the oden_home pointer file."""
    return get_app_support_dir() / POINTER_FILENAME


def get_oden_home_path() -> Path | None:
    """Get the Oden home directory path.

    Resolution order:
    1. ODEN_HOME environment variable (highest priority, for Docker)
    2. Pointer file (oden_home.txt in platform app-support dir)

    Returns:
        Path to the Oden home directory, or None if:
        - No ODEN_HOME env var and no pointer file
        - Pointer file is empty
        - Pointed directory doesn't exist
    """
    import os

    # Check ODEN_HOME environment variable first (used in Docker)
    env_home = os.environ.get("ODEN_HOME")
    if env_home:
        try:
            oden_home = normalize_path(env_home)
            # Create the directory if it doesn't exist (Docker volumes)
            oden_home.mkdir(parents=True, exist_ok=True)
            return oden_home
        except (OSError, ValueError) as e:
            logger.error(f"Invalid ODEN_HOME environment variable '{env_home}': {e}")

    pointer_file = get_pointer_file_path()

    if not pointer_file.exists():
        return None

    try:
        content = pointer_file.read_text(encoding="utf-8").strip()
        if not content:
            return None

        oden_home = normalize_path(content)

        # Verify the directory exists
        if not oden_home.exists():
            logger.warning(f"Oden home directory does not exist: {oden_home}")
            return None

        return oden_home

    except (OSError, ValueError) as e:
        logger.error(f"Error reading pointer file: {e}")
        return None


def set_oden_home_path(path: Path) -> bool:
    """Set the Oden home directory path in the pointer file.

    Args:
        path: Path to the Oden home directory.

    Returns:
        True if successful, False otherwise.
    """
    pointer_file = get_pointer_file_path()

    # Create app support directory if needed using centralized function
    success, error = ensure_directory(pointer_file.parent)
    if not success:
        logger.error(f"Failed to create directory: {error}")
        return False

    try:
        # Write the path
        pointer_file.write_text(str(path.resolve()), encoding="utf-8")
        logger.info(f"Set Oden home path to: {path}")
        return True

    except OSError as e:
        logger.error(f"Error writing pointer file: {e}")
        return False


def validate_oden_home(path: Path) -> tuple[bool, str | None]:
    """Validate an Oden home directory.

    Checks if:
    1. The directory exists (or can be created)
    2. The config.db file exists and is valid (if present)

    Args:
        path: Path to validate as Oden home directory.

    Returns:
        (True, None) if valid or can be set up
        (False, error_code) if invalid:
            - "not_writable": Cannot create or write to directory
            - "corrupt": config.db exists but is corrupted
            - "invalid_schema": config.db has wrong schema
    """
    from oden.config_db import check_db_integrity

    try:
        path = normalize_path(path)
    except (OSError, ValueError):
        return False, "not_writable"

    # Check if we can create/access the directory
    success, _error = ensure_directory(path)
    if not success:
        return False, "not_writable"

    if not path.is_dir():
        return False, "not_writable"

    # Check if config.db exists and is valid
    db_path = path / "config.db"
    if db_path.exists():
        is_valid, error = check_db_integrity(db_path)
        if not is_valid:
            return False, error

    return True, None


def clear_oden_home_pointer() -> bool:
    """Clear the Oden home pointer file.

    Used when resetting configuration.

    Returns:
        True if successful, False otherwise.
    """
    pointer_file = get_pointer_file_path()

    try:
        if pointer_file.exists():
            pointer_file.unlink()
            logger.info("Cleared Oden home pointer file")
        return True
    except OSError as e:
        logger.error(f"Error clearing pointer file: {e}")
        return False
