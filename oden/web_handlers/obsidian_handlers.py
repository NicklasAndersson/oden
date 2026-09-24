"""Obsidian vault handlers: install Oden's Obsidian settings into the vault.

The vault path and directory structure themselves are ordinary config keys,
saved through ``/api/config-save`` from the Obsidian tab.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from aiohttp import web

from oden import config as cfg
from oden.bundle_utils import get_bundle_path
from oden.web_handlers._helpers import handle_errors

logger = logging.getLogger(__name__)


def _template_dir() -> Path | None:
    for candidate in (get_bundle_path() / "obsidian-template" / ".obsidian", Path("./obsidian-template/.obsidian")):
        if candidate.is_dir():
            return candidate
    return None


@handle_errors("obsidian status")
async def obsidian_status_handler(request: web.Request) -> web.Response:
    vault = Path(str(cfg.VAULT_PATH)).expanduser()
    return web.json_response(
        {
            "vault_path": str(vault),
            "vault_exists": vault.is_dir(),
            "obsidian_installed": (vault / ".obsidian").is_dir(),
            "template_available": _template_dir() is not None,
        }
    )


@handle_errors("install obsidian template")
async def obsidian_install_template_handler(request: web.Request) -> web.Response:
    """Copy Oden's .obsidian settings (Map View etc.) into the configured vault.

    An existing ``.obsidian`` folder is never overwritten — it holds the
    operator's own Obsidian settings.
    """
    vault = Path(str(cfg.VAULT_PATH)).expanduser()
    target = vault / ".obsidian"
    if target.exists():
        return web.json_response(
            {"success": True, "skipped": True, "message": "Valvet har redan Obsidian-inställningar — inget ändrat."}
        )

    template = _template_dir()
    if template is None:
        return web.json_response({"success": False, "error": "Obsidian-mallen hittades inte"}, status=404)

    try:
        vault.mkdir(parents=True, exist_ok=True)
        shutil.copytree(template, target)
    except PermissionError as exc:
        return web.json_response({"success": False, "error": f"Behörighetsproblem: {exc}"}, status=500)

    logger.info("Installerade Obsidian-mallen i %s", target)
    return web.json_response(
        {
            "success": True,
            "message": "Obsidian-inställningar installerade. Aktivera community plugins i Obsidian för Map View.",
            "path": str(target),
        }
    )
