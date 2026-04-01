"""
Web server for Oden GUI.

Provides a web interface for viewing config, logs, sending commands,
and initial setup wizard for first-run configuration.
"""

import asyncio
import logging

import aiohttp_jinja2
import jinja2
from aiohttp import web

from oden import __version__
from oden import config as cfg
from oden.log_buffer import get_log_buffer
from oden.web_handlers import (
    accept_invitation_handler,
    accounts_activate_handler,
    accounts_delete_handler,
    accounts_devices_handler,
    accounts_force_delete_handler,
    accounts_link_cancel_handler,
    accounts_link_handler,
    accounts_link_status_handler,
    accounts_list_handler,
    config_handler,
    config_reset_handler,
    config_save_handler,
    contacts_handler,
    contacts_refresh_handler,
    decline_invitation_handler,
    groups_handler,
    invitations_handler,
    join_group_handler,
    refresh_groups_handler,
    response_create_handler,
    response_delete_handler,
    response_get_handler,
    response_save_handler,
    responses_list_handler,
    setup_cancel_link_handler,
    setup_handler,
    setup_install_obsidian_template_handler,
    setup_oden_home_handler,
    setup_reset_config_handler,
    setup_save_config_handler,
    setup_start_link_handler,
    setup_start_register_handler,
    setup_status_handler,
    setup_validate_path_handler,
    setup_verify_code_handler,
    signal_config_handler,
    signal_config_save_handler,
    template_export_handler,
    template_get_handler,
    template_preview_handler,
    template_reset_handler,
    template_save_handler,
    templates_export_all_handler,
    templates_list_handler,
    toggle_ignore_group_handler,
    toggle_whitelist_group_handler,
    update_contact_handler,
    update_group_handler,
)

logger = logging.getLogger(__name__)


async def index_handler(request: web.Request) -> web.Response:
    """Serve the main HTML page."""
    return aiohttp_jinja2.render_template("dashboard.html", request, {"version": __version__})


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
        from oden.app_state import get_app_state

        get_app_state().request_quit()

    asyncio.create_task(delayed_shutdown())

    return response


def create_app(setup_mode: bool = False) -> web.Application:
    """Create and configure the aiohttp application.

    Args:
        setup_mode: If True, only enable setup-related routes.
    """
    app = web.Application()

    # Set up Jinja2 template engine for HTML rendering
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.PackageLoader("oden", "templates/web"),
        autoescape=jinja2.select_autoescape(["html"]),
    )

    # Setup routes (always available)
    app.router.add_get("/setup", setup_handler)
    app.router.add_get("/api/setup/status", setup_status_handler)
    app.router.add_post("/api/setup/start-link", setup_start_link_handler)
    app.router.add_post("/api/setup/cancel-link", setup_cancel_link_handler)
    app.router.add_post("/api/setup/save-config", setup_save_config_handler)
    app.router.add_post("/api/setup/start-register", setup_start_register_handler)
    app.router.add_post("/api/setup/verify-code", setup_verify_code_handler)
    app.router.add_post("/api/setup/install-obsidian-template", setup_install_obsidian_template_handler)
    app.router.add_post("/api/setup/oden-home", setup_oden_home_handler)
    app.router.add_post("/api/setup/validate-path", setup_validate_path_handler)
    app.router.add_delete("/api/setup/reset", setup_reset_config_handler)
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
        app.router.add_post("/api/groups/refresh", refresh_groups_handler)
        app.router.add_post("/api/groups/update", update_group_handler)
        app.router.add_post("/api/toggle-ignore-group", toggle_ignore_group_handler)
        app.router.add_post("/api/toggle-whitelist-group", toggle_whitelist_group_handler)
        app.router.add_post("/api/config-save", config_save_handler)
        app.router.add_delete("/api/config/reset", config_reset_handler)
        app.router.add_post("/api/shutdown", shutdown_handler)

        # Account management routes
        app.router.add_get("/api/accounts", accounts_list_handler)
        app.router.add_post("/api/accounts/link", accounts_link_handler)
        app.router.add_get("/api/accounts/link-status", accounts_link_status_handler)
        app.router.add_post("/api/accounts/link-cancel", accounts_link_cancel_handler)
        app.router.add_post("/api/accounts/activate", accounts_activate_handler)
        app.router.add_delete("/api/accounts/{number}", accounts_delete_handler)
        app.router.add_delete("/api/accounts/{number}/force", accounts_force_delete_handler)
        app.router.add_get("/api/accounts/devices", accounts_devices_handler)

        # Contact routes
        app.router.add_get("/api/contacts", contacts_handler)
        app.router.add_post("/api/contacts/refresh", contacts_refresh_handler)
        app.router.add_put("/api/contacts/{number}", update_contact_handler)

        # Signal protocol config routes
        app.router.add_get("/api/signal-config", signal_config_handler)
        app.router.add_post("/api/signal-config", signal_config_save_handler)

        # Response (auto-reply) routes
        app.router.add_get("/api/responses", responses_list_handler)
        app.router.add_post("/api/responses/new", response_create_handler)
        app.router.add_get("/api/responses/{id}", response_get_handler)
        app.router.add_post("/api/responses/{id}", response_save_handler)
        app.router.add_delete("/api/responses/{id}", response_delete_handler)

        # Template routes
        app.router.add_get("/api/templates", templates_list_handler)
        app.router.add_get("/api/templates/export", templates_export_all_handler)
        app.router.add_get("/api/templates/{name}", template_get_handler)
        app.router.add_post("/api/templates/{name}", template_save_handler)
        app.router.add_post("/api/templates/{name}/preview", template_preview_handler)
        app.router.add_post("/api/templates/{name}/reset", template_reset_handler)
        app.router.add_get("/api/templates/{name}/export", template_export_handler)

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
    if cfg.WEB_ACCESS_LOG and not setup_mode:
        access_log = logging.getLogger("aiohttp.access")
        access_log.setLevel(logging.INFO)
        # Remove any existing handlers to avoid duplicate output
        access_log.handlers.clear()
        access_log.propagate = False
        # Add file handler
        file_handler = logging.FileHandler(cfg.WEB_ACCESS_LOG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        access_log.addHandler(file_handler)

    runner = web.AppRunner(app, access_log=access_log)
    await runner.setup()
    site = web.TCPSite(runner, cfg.WEB_HOST, port)
    await site.start()
    mode_str = " (setup mode)" if setup_mode else ""
    logger.info(f"Web GUI started at http://{cfg.WEB_HOST}:{port}{mode_str}")
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
    from oden.config import is_configured, validate_signal_number

    runner = await start_web_server(port, setup_mode=True)
    try:
        # Poll for configuration completion.
        # Only call validate_signal_number() when is_configured() first
        # returns True (transition), to avoid scanning accounts from disk
        # every second while waiting.
        configured, _error = is_configured()
        if configured:
            _valid, _verr, _accts = validate_signal_number()
            if not _valid:
                configured, _error = False, _verr
        if not configured:
            logger.info("Waiting for setup to complete (reason: %s)...", _error)
        was_configured = configured
        while not configured:
            await asyncio.sleep(1.0)
            configured, _error = is_configured()
            if configured and not was_configured:
                _valid, _verr, _accts = validate_signal_number()
                if not _valid:
                    configured, _error = False, _verr
            was_configured = configured
        logger.info("Setup completed, configuration saved.")
        # Wait so the browser can show success message and redirect
        await asyncio.sleep(5.0)
        return True
    finally:
        await runner.cleanup()
