"""
Path handling utilities for security and consistency.

Provides centralized functions for path validation, sanitization, and
directory operations to prevent directory traversal attacks and ensure
consistent path handling across the codebase.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def normalize_path(path: str | Path) -> Path:
    """Expand user (~) and resolve path to absolute form.

    Args:
        path: User-provided path string or Path object.

    Returns:
        Normalized, resolved absolute Path.

    Raises:
        ValueError: If path is empty.
        OSError: If path cannot be resolved.
    """
    if path is None or (isinstance(path, str) and not path.strip()):
        raise ValueError("Path cannot be empty")
    return Path(path).expanduser().resolve()


def is_within_directory(path: Path, parent: Path) -> bool:
    """Check if path is within (or equal to) parent directory.

    Prevents directory traversal attacks by verifying a path doesn't
    escape its intended parent directory.

    Args:
        path: Path to check (should be resolved/normalized).
        parent: Parent directory (should be resolved/normalized).

    Returns:
        True if path is within or equal to parent directory.
    """
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def is_filesystem_root(path: Path) -> bool:
    """Check if path is the filesystem root.

    Args:
        path: Path to check (should be resolved).

    Returns:
        True if path is the filesystem root (/ on Unix, C:\\ on Windows).
    """
    return str(path) == path.anchor


def validate_path_within_home(
    path: str | Path,
    allow_path: Path | None = None,
) -> tuple[Path | None, str | None]:
    """Validate a user-provided path is within user's home directory.

    When the ODEN_HOME environment variable is set (e.g. Docker), the
    home-directory constraint is relaxed — only the filesystem root check
    is enforced.

    Args:
        path: User-provided path.
        allow_path: Optional specific path to allow even if outside home.

    Returns:
        (normalized_path, None) on success.
        (None, error_message) on failure.
    """
    try:
        resolved = normalize_path(path)
    except (OSError, RuntimeError, ValueError) as e:
        return None, f"Ogiltig sökväg: {e}"

    if is_filesystem_root(resolved):
        logger.warning("Path rejected: filesystem root is not allowed")
        return None, "Sökväg kan inte vara filsystemets rot"

    # When ODEN_HOME is set (Docker), skip the home-directory constraint
    if os.environ.get("ODEN_HOME"):
        return resolved, None

    # Allow specific whitelisted path
    if allow_path is not None:
        try:
            allowed = normalize_path(allow_path)
            if resolved == allowed:
                return resolved, None
        except (OSError, RuntimeError, ValueError):
            pass

    # Must be within user's home directory
    try:
        user_home = Path.home().resolve()
        if not is_within_directory(resolved, user_home):
            logger.warning("Path rejected: %s is outside home directory %s", resolved, user_home)
            return None, f"Sökväg måste vara under {user_home}"
    except (OSError, RuntimeError):
        return None, "Kunde inte verifiera hemkatalog"

    return resolved, None


def ensure_directory(path: Path | str, parents: bool = True) -> tuple[bool, str | None]:
    """Safely create a directory.

    Args:
        path: Directory path to create.
        parents: Create parent directories if needed.

    Returns:
        (True, None) on success.
        (False, error_message) on failure.
    """
    try:
        Path(path).mkdir(parents=parents, exist_ok=True)
        return True, None
    except PermissionError:
        logger.warning("Permission denied creating directory: %s", path)
        return False, "Behörighet nekad"
    except OSError as e:
        logger.warning("Failed to create directory %s: %s", path, e)
        return False, f"Kunde inte skapa katalog: {e}"
