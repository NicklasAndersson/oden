"""
Web server for Oden GUI.

Provides a web interface for viewing config, logs, sending commands,
and initial setup wizard for first-run configuration.
"""

import asyncio
import logging
import os
import signal

from aiohttp import web

from oden import __version__
from oden.config import WEB_ACCESS_LOG
from oden.log_buffer import get_log_buffer
from oden.web_handlers import (
    accept_invitation_handler,
    config_file_get_handler,
    config_file_save_handler,
    config_handler,
    config_save_handler,
    decline_invitation_handler,
    groups_handler,
    invitations_handler,
    join_group_handler,
    setup_cancel_link_handler,
    setup_handler,
    setup_install_obsidian_template_handler,
    setup_save_config_handler,
    setup_start_link_handler,
    setup_start_register_handler,
    setup_status_handler,
    setup_verify_code_handler,
    toggle_ignore_group_handler,
    toggle_whitelist_group_handler,
)
from oden.web_templates import HTML_TEMPLATE

logger = logging.getLogger(__name__)


async def index_handler(request: web.Request) -> web.Response:
    """Serve the main HTML page."""
    html = HTML_TEMPLATE.replace("{{version}}", __version__)
    return web.Response(text=html, content_type="text/html")


async def logs_handler(request: web.Request) -> web.Response:
    """Return buffered log entries as JSON."""
    log_buffer = get_log_buffer()
    entries = log_buffer.get_entries()
    return web.json_response(entries)


async def shutdown_handler(request: web.Request) -> web.Response:
    """Shutdown the application gracefully."""
    logger.info("Shutdown requested via web GUI")

    # Send response before shutting down
    response = web.json_response({"success": True, "message": "Stänger av..."})

    # Schedule shutdown after response is sent
    async def delayed_shutdown():
        await asyncio.sleep(0.5)  # Give time for response to be sent
        logger.info("Initiating shutdown...")
        # Raise SystemExit to trigger graceful shutdown
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(delayed_shutdown())

    return response


def create_app(setup_mode: bool = False) -> web.Application:
    """Create and configure the aiohttp application.

    Args:
        setup_mode: If True, only enable setup-related routes.
    """
    app = web.Application()

    # Setup routes (always available)
    app.router.add_get("/setup", setup_handler)
    app.router.add_get("/api/setup/status", setup_status_handler)
    app.router.add_post("/api/setup/start-link", setup_start_link_handler)
    app.router.add_post("/api/setup/cancel-link", setup_cancel_link_handler)
    app.router.add_post("/api/setup/save-config", setup_save_config_handler)
    app.router.add_post("/api/setup/start-register", setup_start_register_handler)
    app.router.add_post("/api/setup/verify-code", setup_verify_code_handler)
    app.router.add_post("/api/setup/install-obsidian-template", setup_install_obsidian_template_handler)

    if setup_mode:
        # In setup mode, redirect root to setup
        async def redirect_to_setup(request):
            raise web.HTTPFound("/setup")

        app.router.add_get("/", redirect_to_setup)
    else:
        # Normal mode routes
        app.router.add_get("/", index_handler)
        app.router.add_get("/api/config", config_handler)
        app.router.add_get("/api/logs", logs_handler)
        app.router.add_post("/api/join-group", join_group_handler)
        app.router.add_get("/api/invitations", invitations_handler)
        app.router.add_post("/api/invitations/accept", accept_invitation_handler)
        app.router.add_post("/api/invitations/decline", decline_invitation_handler)
        app.router.add_get("/api/groups", groups_handler)
        app.router.add_post("/api/toggle-ignore-group", toggle_ignore_group_handler)
        app.router.add_post("/api/toggle-whitelist-group", toggle_whitelist_group_handler)
        app.router.add_get("/api/config-file", config_file_get_handler)
        app.router.add_post("/api/config-file", config_file_save_handler)
        app.router.add_post("/api/config-save", config_save_handler)
        app.router.add_post("/api/shutdown", shutdown_handler)

    return app


async def start_web_server(port: int = 8080, setup_mode: bool = False) -> web.AppRunner:
    """Start the web server on the specified port.

    Args:
        port: Port to listen on (default 8080).
        setup_mode: If True, only enable setup-related routes.

    Returns:
        The AppRunner instance (for cleanup).
    """
    app = create_app(setup_mode=setup_mode)

    # Configure access logger to write to file instead of terminal
    access_log: logging.Logger | None = None
    if WEB_ACCESS_LOG and not setup_mode:
        access_log = logging.getLogger("aiohttp.access")
        access_log.setLevel(logging.INFO)
        # Remove any existing handlers to avoid duplicate output
        access_log.handlers.clear()
        access_log.propagate = False
        # Add file handler
        file_handler = logging.FileHandler(WEB_ACCESS_LOG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        access_log.addHandler(file_handler)

    runner = web.AppRunner(app, access_log=access_log)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    mode_str = " (setup mode)" if setup_mode else ""
    logger.info(f"Web GUI started at http://127.0.0.1:{port}{mode_str}")
    return runner


async def run_web_server(port: int = 8080, setup_mode: bool = False) -> None:
    """Run the web server indefinitely.

    This function starts the web server and waits forever.
    Use this with asyncio.gather() to run alongside other tasks.

    Args:
        port: Port to listen on.
        setup_mode: If True, only enable setup-related routes.
    """
    runner = await start_web_server(port, setup_mode=setup_mode)
    try:
        # Wait forever
        await asyncio.sleep(float("inf"))
    finally:
        await runner.cleanup()


async def run_setup_server(port: int = 8080) -> bool:
    """Run the web server in setup mode until configuration is complete.

    Args:
        port: Port to listen on.

    Returns:
        True if setup completed successfully, False otherwise.
    """
    from oden.config import is_configured

    runner = await start_web_server(port, setup_mode=True)
    try:
        # Poll for configuration completion
        while not is_configured():
            await asyncio.sleep(1.0)
        logger.info("Setup completed, configuration saved.")
        # Wait so the browser can show success message and redirect
        await asyncio.sleep(5.0)
        return True
    finally:
        await runner.cleanup()
