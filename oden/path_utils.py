"""
Path handling utilities for security and consistency.

Provides centralized functions for path validation, sanitization, and
directory operations to prevent directory traversal attacks and ensure
consistent path handling across the codebase.
"""

import os
import re
from pathlib import Path

# Characters not allowed in filenames (cross-platform safe)
UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


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
    if not path:
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
        return None, "Sökväg kan inte vara filsystemets rot"

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
            return None, f"Sökväg måste vara under {user_home}"
    except (OSError, RuntimeError):
        return None, "Kunde inte verifiera hemkatalog"

    return resolved, None


def validate_path_within_directory(
    path: str | Path,
    parent: Path,
) -> tuple[Path | None, str | None]:
    """Validate a user-provided path is within a specific directory.

    Args:
        path: User-provided path (can be relative to parent).
        parent: Parent directory the path must be within.

    Returns:
        (normalized_path, None) on success.
        (None, error_message) on failure.
    """
    try:
        parent_resolved = normalize_path(parent)
        # Resolve relative to parent to handle relative paths safely
        resolved = (parent_resolved / path).resolve()
    except (OSError, RuntimeError, ValueError) as e:
        return None, f"Ogiltig sökväg: {e}"

    if not is_within_directory(resolved, parent_resolved):
        return None, f"Sökväg måste vara under {parent_resolved}"

    return resolved, None


def validate_ini_file_path(
    path: str | Path,
    must_be_within: Path | None = None,
) -> tuple[Path | None, str | None]:
    """Validate a path points to a valid INI file.

    Args:
        path: Path to INI file.
        must_be_within: If set, INI file must be within this directory.

    Returns:
        (normalized_path, None) on success.
        (None, error_message) on failure.
    """
    try:
        resolved = normalize_path(path)
    except (OSError, RuntimeError, ValueError) as e:
        return None, f"Ogiltig sökväg för INI-fil: {e}"

    # Check parent constraint
    if must_be_within is not None:
        try:
            parent = normalize_path(must_be_within)
            if not is_within_directory(resolved, parent):
                return None, f"INI-fil måste vara under {parent}"
        except (OSError, RuntimeError, ValueError):
            return None, "Ogiltig föräldrasökväg"

    # Must be named config.ini
    if resolved.name != "config.ini":
        return None, f"INI-fil måste heta config.ini, inte {resolved.name}"

    # Must exist and be a file
    if not resolved.exists():
        return None, f"INI-fil hittades inte: {resolved}"

    if not resolved.is_file():
        return None, f"Sökvägen är inte en fil: {resolved}"

    return resolved, None


def sanitize_filename(filename: str, fallback: str = "unnamed") -> str:
    """Sanitize a filename to prevent path traversal and invalid characters.

    Strips directory components and replaces unsafe characters.

    Args:
        filename: User-provided filename.
        fallback: Name to use if filename becomes empty after sanitization.

    Returns:
        Safe filename with only the base name.
    """
    if not filename:
        return fallback

    # Get basename to strip any path components (handles both / and \\)
    safe = os.path.basename(filename)

    # Also handle if someone tries ../../ style paths
    safe = safe.replace("..", "")

    # Remove unsafe characters
    safe = UNSAFE_FILENAME_CHARS.sub("_", safe)

    # Strip leading/trailing whitespace and dots
    safe = safe.strip(". \t\n\r")

    # If empty after sanitization, use fallback
    if not safe:
        return fallback

    return safe


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
        return False, "Behörighet nekad"
    except OSError as e:
        return False, f"Kunde inte skapa katalog: {e}"
