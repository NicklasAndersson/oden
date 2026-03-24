"""
Contact management handlers for Oden web GUI.

Provides endpoints for listing cached contacts and refreshing from signal-cli.
"""

import logging

from aiohttp import web

from oden import config as cfg
from oden.app_state import get_app_state

logger = logging.getLogger(__name__)


async def contacts_handler(request: web.Request) -> web.Response:
    """Return cached contacts as JSON."""
    app_state = get_app_state()
    contacts = list(app_state.contacts.values())
    return web.json_response({"contacts": contacts})


async def contacts_refresh_handler(request: web.Request) -> web.Response:
    """Refresh contacts from signal-cli and return updated list."""
    app_state = get_app_state()

    try:
        response = await app_state.send_jsonrpc(
            "listContacts",
            params={"account": cfg.SIGNAL_NUMBER, "allRecipients": True},
            timeout=10.0,
        )
        if response and "result" in response:
            contacts = response["result"]
            app_state.update_contacts(contacts)
            return web.json_response(
                {
                    "success": True,
                    "contacts": list(app_state.contacts.values()),
                }
            )
        return web.json_response(
            {"success": False, "error": "Inget svar från signal-cli"},
            status=502,
        )
    except Exception as e:
        logger.error("Failed to refresh contacts: %s", e)
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500,
        )
