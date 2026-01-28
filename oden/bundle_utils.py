"""
Utility functions for handling PyInstaller bundles and bundled resources.

This module provides functions for detecting if the application is running
as a PyInstaller bundle and accessing bundled resources.
"""

import logging
import platform
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


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
