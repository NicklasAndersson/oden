"""
Shared helpers and decorators for web handlers.

Reduces boilerplate for common patterns: JSON body parsing, connection
checks, and error handling.
"""

import functools
import json
import logging

from aiohttp import web

from oden import config as cfg
from oden.app_state import get_app_state
from oden.config import reload_config
from oden.config_db import set_config_value

logger = logging.getLogger(__name__)


def parse_json_body(handler):
    """Decorator: parse JSON body and store in ``request["json_body"]``.

    Returns 400 with a Swedish error message on invalid JSON.
    """

    @functools.wraps(handler)
    async def wrapper(request: web.Request) -> web.Response:
        try:
            request["json_body"] = await request.json()
        except (json.JSONDecodeError, Exception):
            return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
        return await handler(request)

    return wrapper


def require_writer(handler):
    """Decorator: require an active signal-cli connection (``app_state.writer``).

    Returns 503 when the writer is unavailable.
    """

    @functools.wraps(handler)
    async def wrapper(request: web.Request) -> web.Response:
        app_state = get_app_state()
        if not app_state.writer:
            return web.json_response(
                {"success": False, "error": "Inte ansluten till signal-cli"},
                status=503,
            )
        return await handler(request)

    return wrapper


def handle_errors(context: str):
    """Decorator factory: wrap handler in try/except with logging.

    *context* is a short description used in the log message, e.g.
    ``"toggle ignore group"``.
    """

    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(request: web.Request) -> web.Response:
            try:
                return await handler(request)
            except json.JSONDecodeError:
                return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
            except Exception as e:
                logger.error("Error %s: %s", context, e)
                return web.json_response({"success": False, "error": str(e)}, status=500)

        return wrapper

    return decorator


def update_config_and_reload(key: str, value) -> None:
    """Persist a single config value and trigger live reload."""
    set_config_value(cfg.CONFIG_DB, key, value)
    reload_config()
