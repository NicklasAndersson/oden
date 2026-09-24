"""
Web server for Oden GUI.

Provides a web interface for viewing config, logs, sending commands,
and initial setup wizard for first-run configuration.
"""

import asyncio
import base64
import logging
from pathlib import Path

import aiohttp_jinja2
import jinja2
from aiohttp import web

from oden import __version__
from oden import config as cfg
from oden.bundle_utils import get_bundle_path
from oden.log_buffer import get_log_buffer
from oden.signal_log_monitor import get_signal_log_status
from oden.signal_manager import (
    EXPECTED_SIGNAL_CLI_VERSION,
    find_signal_cli_executable,
    get_signal_cli_version,
    is_signal_cli_version_older,
)
from oden.web_handlers.account_handlers import (
    accounts_activate_handler,
    accounts_delete_handler,
    accounts_devices_handler,
    accounts_force_delete_handler,
    accounts_link_cancel_handler,
    accounts_link_handler,
    accounts_link_status_handler,
    accounts_list_handler,
)
from oden.web_handlers.config_handlers import (
    config_handler,
    config_reset_handler,
    config_save_handler,
    oden_home_change_handler,
    oden_home_handler,
    signal_config_handler,
    signal_config_save_handler,
    storage_cleanup_handler,
    storage_handler,
)
from oden.web_handlers.contact_handlers import (
    contacts_handler,
    contacts_refresh_handler,
    update_contact_handler,
)
from oden.web_handlers.format_handlers import format_test_handler, formats_handler, formats_save_handler
from oden.web_handlers.group_handlers import (
    accept_invitation_handler,
    create_group_handler,
    decline_invitation_handler,
    groups_handler,
    invitations_handler,
    join_group_handler,
    refresh_groups_handler,
    update_group_handler,
)
from oden.web_handlers.message_handlers import (
    flow_detail_handler,
    flow_list_handler,
    message_detail_handler,
    message_reprocess_handler,
    message_stats_handler,
    messages_list_handler,
)
from oden.web_handlers.obsidian_handlers import obsidian_install_template_handler, obsidian_status_handler
from oden.web_handlers.pipeline_handlers import (
    list_pipelines,
    reorder_pipelines,
    toggle_pipeline,
    update_pipeline_config,
)
from oden.web_handlers.response_handlers import (
    response_create_handler,
    response_delete_handler,
    response_get_handler,
    response_save_handler,
    responses_list_handler,
)
from oden.web_handlers.routing_handlers import routing_handler, routing_save_handler, routing_test_handler
from oden.web_handlers.signal_connect_handlers import (
    signal_connect_status_handler,
    signal_disable_handler,
    signal_link_cancel_handler,
    signal_link_start_handler,
    signal_register_start_handler,
    signal_register_verify_handler,
    signal_use_account_handler,
)
from oden.web_handlers.tak_handlers import (
    tak_qr_handler,
    tak_settings_handler,
    tak_settings_save_handler,
    tak_status_handler,
    tak_test_handler,
    tak_upload_cert_handler,
    tak_upload_package_handler,
)
from oden.web_handlers.template_handlers import (
    template_export_handler,
    template_get_handler,
    template_preview_handler,
    template_reset_handler,
    template_save_handler,
    templates_export_all_handler,
    templates_list_handler,
)

logger = logging.getLogger(__name__)


def _resolve_logo_path(bundle_path: Path) -> Path | None:
    """Resolve the preferred web GUI logo path.

    Prefer the current logo asset first, then legacy fallbacks.
    """
    candidates = [
        bundle_path / "images" / "logo.png",
        bundle_path / "images" / "oden_1024.png",
        bundle_path / "images" / "logo_small.jpg",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


async def index_handler(request: web.Request) -> web.Response:
    """Serve the main HTML page."""
    return aiohttp_jinja2.render_template(
        "dashboard.html",
        request,
        {
            "version": __version__,
            "expected_signal_cli_version": EXPECTED_SIGNAL_CLI_VERSION,
            "signal_enabled": cfg.SIGNAL_ENABLED,
            "signal_off_reason": cfg.SIGNAL_OFF_REASON,
        },
    )


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


async def restart_signal_cli_handler(request: web.Request) -> web.Response:
    """Restart managed signal-cli without shutting down Oden."""
    logger.info("signal-cli restart requested via web GUI")

    from oden.app_state import get_app_state

    app_state = get_app_state()
    if app_state.signal_manager is None:
        return web.json_response(
            {
                "success": False,
                "error": "signal-cli hanteras inte av Oden (ohanterad/external mode)",
            },
            status=400,
        )

    # Stop now and schedule start shortly after to ensure a clean restart.
    app_state.request_stop()
    loop = asyncio.get_running_loop()
    loop.call_later(1.0, app_state.request_start)

    return web.json_response({"success": True, "message": "Startar om signal-cli..."})


async def signal_cli_status_handler(request: web.Request) -> web.Response:
    """Return local signal-cli runtime status without external lookups."""
    try:
        executable = find_signal_cli_executable()
    except FileNotFoundError:
        executable = None

    detected_version = get_signal_cli_version(executable)
    version_status = "unknown"
    version_message = "Kunde inte läsa signal-cli-version."

    if detected_version:
        if is_signal_cli_version_older(detected_version, EXPECTED_SIGNAL_CLI_VERSION):
            version_status = "mismatch"
            version_message = (
                f"Installerad signal-cli ({detected_version}) är äldre än Oden-förväntan "
                f"({EXPECTED_SIGNAL_CLI_VERSION})."
            )
        else:
            version_status = "ok"
            version_message = f"signal-cli {detected_version} matchar Oden-förväntan."

    return web.json_response(
        {
            "success": True,
            "expected_version": EXPECTED_SIGNAL_CLI_VERSION,
            "detected_version": detected_version,
            "version_status": version_status,
            "version_message": version_message,
            "executable": executable,
            "log_monitor": get_signal_log_status(),
        }
    )


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()

    # Set up Jinja2 template engine for HTML rendering
    env = aiohttp_jinja2.setup(
        app,
        loader=jinja2.PackageLoader("oden", "templates/web"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    logo_path = _resolve_logo_path(get_bundle_path())
    if logo_path is not None:
        mime_type = "image/jpeg" if logo_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        env.globals["oden_logo_uri"] = f"data:{mime_type};base64," + base64.b64encode(logo_path.read_bytes()).decode()

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
    app.router.add_post("/api/groups/create", create_group_handler)
    app.router.add_post("/api/config-save", config_save_handler)
    app.router.add_delete("/api/config/reset", config_reset_handler)
    app.router.add_get("/api/oden-home", oden_home_handler)
    app.router.add_get("/api/storage", storage_handler)
    app.router.add_get("/api/routing", routing_handler)
    app.router.add_put("/api/routing", routing_save_handler)
    app.router.add_post("/api/pipelines/test", routing_test_handler)
    app.router.add_get("/api/report-formats", formats_handler)
    app.router.add_put("/api/report-formats", formats_save_handler)
    app.router.add_post("/api/report-formats/test", format_test_handler)
    app.router.add_post("/api/storage/cleanup", storage_cleanup_handler)
    app.router.add_post("/api/oden-home", oden_home_change_handler)
    app.router.add_post("/api/signal-cli/restart", restart_signal_cli_handler)
    app.router.add_get("/api/signal-cli/status", signal_cli_status_handler)
    app.router.add_post("/api/shutdown", shutdown_handler)

    # Message observability routes
    app.router.add_get("/api/messages", messages_list_handler)
    app.router.add_get("/api/flow", flow_list_handler)
    app.router.add_get("/api/flow/{id:\\d+}", flow_detail_handler)
    app.router.add_get("/api/messages/stats", message_stats_handler)
    app.router.add_get("/api/messages/{id:\\d+}", message_detail_handler)
    app.router.add_post("/api/messages/{id:\\d+}/reprocess", message_reprocess_handler)

    # Account management routes
    app.router.add_get("/api/accounts", accounts_list_handler)
    app.router.add_post("/api/accounts/link", accounts_link_handler)
    app.router.add_get("/api/accounts/link-status", accounts_link_status_handler)
    app.router.add_post("/api/accounts/link-cancel", accounts_link_cancel_handler)
    app.router.add_post("/api/accounts/activate", accounts_activate_handler)
    app.router.add_delete("/api/accounts/{number}", accounts_delete_handler)
    app.router.add_delete("/api/accounts/{number}/force", accounts_force_delete_handler)
    app.router.add_get("/api/accounts/devices", accounts_devices_handler)

    # Pipeline management routes
    app.router.add_get("/api/pipelines", list_pipelines)
    app.router.add_patch("/api/pipelines/{name}/enabled", toggle_pipeline)
    app.router.add_patch("/api/pipelines/{name}/config", update_pipeline_config)
    app.router.add_post("/api/pipelines/reorder", reorder_pipelines)

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

    # TAK integration routes
    app.router.add_get("/api/tak/status", tak_status_handler)
    app.router.add_get("/api/tak/settings", tak_settings_handler)
    app.router.add_post("/api/tak/settings", tak_settings_save_handler)
    app.router.add_post("/api/tak/test", tak_test_handler)
    app.router.add_post("/api/tak/upload-package", tak_upload_package_handler)
    app.router.add_post("/api/tak/upload-cert", tak_upload_cert_handler)
    app.router.add_post("/api/tak/qr", tak_qr_handler)

    # Signal: connect/disconnect from the Signal tab (no daemon needed)
    app.router.add_get("/api/signal/connect/status", signal_connect_status_handler)
    app.router.add_post("/api/signal/connect/link", signal_link_start_handler)
    app.router.add_post("/api/signal/connect/link-cancel", signal_link_cancel_handler)
    app.router.add_post("/api/signal/connect/register", signal_register_start_handler)
    app.router.add_post("/api/signal/connect/verify", signal_register_verify_handler)
    app.router.add_post("/api/signal/connect/use", signal_use_account_handler)
    app.router.add_post("/api/signal/connect/disable", signal_disable_handler)

    # Obsidian vault
    app.router.add_get("/api/obsidian/status", obsidian_status_handler)
    app.router.add_post("/api/obsidian/install-template", obsidian_install_template_handler)
    return app


async def start_web_server(port: int = 8080) -> web.AppRunner:
    """Start the web server on the specified port.

    Args:
        port: Port to listen on (default 8080).

    Returns:
        The AppRunner instance (for cleanup).
    """
    app = create_app()

    # Configure access logger to write to file instead of terminal
    access_log: logging.Logger | None = None
    if cfg.WEB_ACCESS_LOG:
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
    logger.info(f"Web GUI started at http://{cfg.WEB_HOST}:{port}")
    return runner


async def run_web_server(port: int = 8080) -> None:
    """Run the web server indefinitely.

    This function starts the web server and waits forever.
    Use this with asyncio.gather() to run alongside other tasks.

    Args:
        port: Port to listen on.
    """
    runner = await start_web_server(port)
    try:
        # Wait forever
        await asyncio.sleep(float("inf"))
    finally:
        await runner.cleanup()
