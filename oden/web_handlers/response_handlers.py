"""
Web handlers for managing command responses (auto-replies).

Provides CRUD endpoints for the responses table in config_db.
"""

import logging

from aiohttp import web

from oden.config import CONFIG_DB
from oden.config_db import (
    create_response,
    delete_response,
    get_all_responses,
    get_response_by_id,
    save_response,
)

logger = logging.getLogger(__name__)


async def responses_list_handler(request: web.Request) -> web.Response:
    """Return all responses as JSON."""
    try:
        responses = get_all_responses(CONFIG_DB)
        return web.json_response(responses)
    except Exception as e:
        logger.error(f"Error listing responses: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def response_get_handler(request: web.Request) -> web.Response:
    """Return a single response by id."""
    try:
        response_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"success": False, "error": "Ogiltigt id"}, status=400)

    response = get_response_by_id(CONFIG_DB, response_id)
    if response is None:
        return web.json_response({"success": False, "error": "Svar hittades inte"}, status=404)

    return web.json_response(response)


async def response_save_handler(request: web.Request) -> web.Response:
    """Update an existing response."""
    try:
        response_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"success": False, "error": "Ogiltigt id"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)

    keywords = data.get("keywords")
    body = data.get("body")

    if not keywords or not isinstance(keywords, list):
        return web.json_response({"success": False, "error": "Nyckelord krävs (lista)"}, status=400)
    if body is None:
        return web.json_response({"success": False, "error": "Svarstext krävs"}, status=400)

    if save_response(CONFIG_DB, response_id, keywords, body):
        return web.json_response({"success": True, "message": "Svar uppdaterat"})
    else:
        return web.json_response({"success": False, "error": "Kunde inte spara svar"}, status=500)


async def response_create_handler(request: web.Request) -> web.Response:
    """Create a new response."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)

    keywords = data.get("keywords")
    body = data.get("body")

    if not keywords or not isinstance(keywords, list):
        return web.json_response({"success": False, "error": "Nyckelord krävs (lista)"}, status=400)
    if body is None:
        return web.json_response({"success": False, "error": "Svarstext krävs"}, status=400)

    new_id = create_response(CONFIG_DB, keywords, body)
    if new_id is not None:
        return web.json_response({"success": True, "id": new_id, "message": "Svar skapat"})
    else:
        return web.json_response({"success": False, "error": "Kunde inte skapa svar"}, status=500)


async def response_delete_handler(request: web.Request) -> web.Response:
    """Delete a response by id."""
    try:
        response_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"success": False, "error": "Ogiltigt id"}, status=400)

    if delete_response(CONFIG_DB, response_id):
        return web.json_response({"success": True, "message": "Svar borttaget"})
    else:
        return web.json_response({"success": False, "error": "Kunde inte ta bort svar"}, status=404)
