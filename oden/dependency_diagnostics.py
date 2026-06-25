"""Cross-platform startup diagnostics for external runtime dependencies."""

from __future__ import annotations

import importlib
import logging
import os
import platform
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from oden.bundle_utils import get_bundled_java_path, is_bundled
from oden.signal_manager import find_signal_cli_executable

logger = logging.getLogger(__name__)


def _classify_native_load_error(exc: Exception) -> tuple[str, str]:
    text = str(exc).lower()
    if (
        "%1 is not a valid win32 application" in text
        or "not a valid win32 application" in text
        or "wrong architecture" in text
        or "bad cpu type" in text
    ):
        return "wrong_arch", "architecture mismatch between runtime and native dependency"

    if "vcruntime" in text or "msvcp" in text or "api-ms-win-crt" in text:
        return "missing_vc_runtime", "missing Microsoft Visual C++ Redistributable"

    if (
        "unable to load" in text
        or "no such file or directory" in text
        or "cannot open shared object file" in text
        or "image not found" in text
        or "the specified module could not be found" in text
    ):
        return "missing_file", "native file missing, blocked, or not bundled"

    return "unknown", "unknown native loader failure"


@lru_cache(maxsize=1)
def _get_mgrs_converter() -> Any | None:
    """Return an MGRS->LatLon converter, or None if mgrs is unavailable."""
    try:
        import mgrs as mgrs_module

        return mgrs_module.MGRS().toLatLon
    except Exception as exc:
        reason, hint = _classify_native_load_error(exc)
        logger.warning(
            "Dependency check: mgrs unavailable (%s: %s). Original error: %s",
            reason,
            hint,
            exc,
        )
        return None


def _diagnose_java() -> None:
    bundled_java = get_bundled_java_path()
    if bundled_java:
        java_path = Path(bundled_java)
        if sys.platform == "win32" and java_path.suffix.lower() != ".exe":
            logger.warning(
                "Dependency check: Java executable mismatch (%s); expected .exe on Windows",
                bundled_java,
            )
            return

        logger.info("Dependency check: Java available (bundled) at %s", bundled_java)
        return

    system_java = shutil.which("java")
    if system_java:
        logger.info("Dependency check: Java available (system PATH) at %s", system_java)
    else:
        logger.warning("Dependency check: Java not found (bundled missing and PATH lookup failed)")


def _diagnose_signal_cli() -> None:
    try:
        executable = find_signal_cli_executable()
    except FileNotFoundError:
        logger.warning("Dependency check: signal-cli executable not found")
        return
    except Exception as exc:
        logger.warning("Dependency check: signal-cli probe failed: %s", exc)
        return

    path = Path(executable)
    if not path.exists():
        logger.warning("Dependency check: signal-cli path does not exist: %s", executable)
        return

    if sys.platform == "win32":
        ext = path.suffix.lower()
        executable_like = ext in {".bat", ".cmd", ".exe"} or os.access(path, os.X_OK)
    else:
        executable_like = os.access(path, os.X_OK)

    if executable_like:
        logger.info("Dependency check: signal-cli executable available at %s", executable)
    else:
        logger.warning("Dependency check: signal-cli exists but is not executable: %s", executable)


def _diagnose_mgrs() -> None:
    if _get_mgrs_converter() is not None:
        logger.info("Dependency check: mgrs native module loaded")


def _diagnose_optional_ui_deps() -> None:
    missing: list[str] = []
    for mod_name in ("pystray", "PIL"):
        try:
            importlib.import_module(mod_name)
        except Exception:
            missing.append(mod_name)

    if missing:
        logger.info("Dependency check: optional tray deps missing (%s); tray icon may be disabled", ", ".join(missing))
    else:
        logger.info("Dependency check: optional tray deps available (pystray, PIL)")


@lru_cache(maxsize=1)
def run_startup_dependency_diagnostics() -> None:
    """Log a one-time dependency diagnostics summary for current runtime."""
    logger.info(
        "Dependency diagnostics: platform=%s arch=%s bundled=%s",
        platform.system(),
        platform.machine(),
        is_bundled(),
    )
    _diagnose_java()
    _diagnose_signal_cli()
    _diagnose_mgrs()
    _diagnose_optional_ui_deps()
