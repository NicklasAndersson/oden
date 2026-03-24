"""
Contact management handlers for Oden web GUI.

Provides endpoints for listing cached contacts and refreshing from signal-cli.
"""

import logging

from aiohttp import web

from oden import config as cfg
from oden.app_state import get_app_state
from oden.web_handlers._helpers import handle_errors, parse_json_body, require_writer

logger = logging.getLogger(__name__)


async def contacts_handler(request: web.Request) -> web.Response:
    """Return cached contacts as JSON."""
    app_state = get_app_state()
    contacts = list(app_state.contacts.values())
    return web.json_response({"contacts": contacts})


@handle_errors("refresh contacts")
@require_writer
async def contacts_refresh_handler(request: web.Request) -> web.Response:
    """Refresh contacts from signal-cli and return updated list."""
    app_state = get_app_state()

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


@handle_errors("update contact")
@parse_json_body
@require_writer
async def update_contact_handler(request: web.Request) -> web.Response:
    """Update a contact via signal-cli updateContact RPC."""
    number = request.match_info["number"]
    data = request["json_body"]

    params: dict = {"account": cfg.SIGNAL_NUMBER, "recipient": number}

    for field in ("name", "givenName", "familyName", "nickGivenName", "nickFamilyName", "note"):
        if field in data:
            params[field] = str(data[field])

    if "expiration" in data:
        params["expiration"] = int(data["expiration"])

    app_state = get_app_state()
    result = await app_state.send_jsonrpc("updateContact", params=params)

    if result is None:
        return web.json_response(
            {"success": False, "error": "Inget svar från signal-cli"},
            status=502,
        )

    # Refresh contacts cache
    contacts_resp = await app_state.send_jsonrpc(
        "listContacts",
        params={"account": cfg.SIGNAL_NUMBER, "allRecipients": True},
        timeout=10.0,
    )
    if contacts_resp and "result" in contacts_resp:
        app_state.update_contacts(contacts_resp["result"])

    logger.info("Contact %s updated", number)
    return web.json_response({"success": True})
