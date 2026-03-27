"""
Signal-cli listener and message processor.

Main entry point that connects to signal-cli daemon and processes incoming messages.
Supports first-run setup wizard for initial configuration.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import webbrowser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oden.tray import OdenTray

from oden import __version__
from oden.app_state import get_app_state
from oden.config import (
    SIGNAL_CLI_HOST,
    SIGNAL_CLI_PORT,
    SIGNAL_NUMBER,
    UNMANAGED_SIGNAL_CLI,
    WEB_ENABLED,
    WEB_PORT,
    is_configured,
    reload_config,
)
from oden.log_utils import apply_log_level, configure_logging, write_log_level
from oden.signal_listener import subscribe_and_listen
from oden.signal_manager import SignalManager, is_signal_cli_running

logger = logging.getLogger(__name__)


async def _run_lifecycle(
    host: str,
    port: int,
    signal_manager: SignalManager | None,
    tray: OdenTray | None,
) -> None:
    """Long-lived async lifecycle that keeps the web server running.

    The signal-cli listener is started/stopped independently via
    asyncio events stored on AppState.  The web server persists
    across stop/start cycles so the GUI is always reachable.
    """
    from oden.web_server import start_web_server

    app_state = get_app_state()
    loop = asyncio.get_running_loop()

    # Create lifecycle events and store on AppState
    stop_event = asyncio.Event()
    start_event = asyncio.Event()
    quit_event = asyncio.Event()

    app_state.loop = loop
    app_state.stop_event = stop_event
    app_state.start_event = start_event
    app_state.quit_event = quit_event
    app_state.signal_manager = signal_manager

    # Start the web server once — it stays alive for the entire lifetime
    web_runner = None
    if WEB_ENABLED:
        web_runner = await start_web_server(WEB_PORT)
        logger.info(f"Web GUI enabled on port {WEB_PORT}")

    listener_task: asyncio.Task | None = None

    try:
        while not quit_event.is_set():
            # Reset events for this cycle
            stop_event.clear()
            start_event.clear()

            # Start signal-cli if managed
            if signal_manager is not None:
                await asyncio.to_thread(signal_manager.start)
            elif not is_signal_cli_running(host, port):
                logger.error("signal-cli is not running. Please start it manually.")
                if tray is None:
                    break
                logger.info("Waiting for Start from tray menu...")
                if tray is not None:
                    tray.running = False
                # Wait for start or quit
                await _wait_for_event(start_event, quit_event)
                if quit_event.is_set():
                    break
                continue

            # Mark as running
            if tray is not None:
                tray.running = True

            # Run the listener as a cancellable task
            listener_task = asyncio.create_task(subscribe_and_listen(host, port))

            # Wait for either the listener to finish or a stop/quit signal
            stop_waiter = asyncio.create_task(stop_event.wait())
            done, pending = await asyncio.wait(
                {listener_task, stop_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel whichever is still pending
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

            # If the listener finished on its own (disconnect / error),
            # retrieve and log any exception
            if listener_task in done:
                exc = listener_task.exception() if not listener_task.cancelled() else None
                if exc is not None:
                    logger.error("Listener stopped with error: %s", exc)
                else:
                    logger.info("Listener disconnected.")
            listener_task = None

            # Stop signal-cli
            if tray is not None:
                tray.running = False
            if signal_manager is not None:
                await asyncio.to_thread(signal_manager.stop)

            # If no tray, exit after first run
            if tray is None:
                break

            if quit_event.is_set():
                break

            logger.info("Watcher stopped. Use tray menu to Start or Quit.")
            # Wait for user to click Start or Quit
            await _wait_for_event(start_event, quit_event)

    except asyncio.CancelledError:
        logger.info("Lifecycle cancelled.")
    finally:
        # Cancel listener if still running
        if listener_task is not None and not listener_task.done():
            listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await listener_task

        # Stop signal-cli
        if signal_manager is not None:
            await asyncio.to_thread(signal_manager.stop)

        # Clean up web server
        if web_runner is not None:
            await web_runner.cleanup()

        # Clear lifecycle state
        app_state.loop = None
        app_state.stop_event = None
        app_state.start_event = None
        app_state.quit_event = None
        app_state.signal_manager = None

        logger.info("Oden shut down.")


async def _wait_for_event(*events: asyncio.Event) -> None:
    """Wait until any of the given events is set."""
    waiters = [asyncio.create_task(e.wait()) for e in events]
    try:
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for w in waiters:
            w.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await w


async def run_setup_mode(port: int) -> bool:
    """Run setup wizard and wait for configuration to complete.

    Args:
        port: Web server port.

    Returns:
        True if setup completed successfully.
    """
    from oden.web_server import run_setup_server

    logger.info("=" * 60)
    logger.info("🛡️  Välkommen till Oden!")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Oden är inte konfigurerad ännu.")
    logger.info("En webbläsare öppnas nu för att guida dig genom setup.")
    logger.info("")
    logger.info(f"Om webbläsaren inte öppnas, gå till: http://127.0.0.1:{port}/setup")
    logger.info("")

    # Open browser after a short delay
    async def open_browser():
        await asyncio.sleep(1.0)
        url = f"http://127.0.0.1:{port}/setup"
        try:
            webbrowser.open(url)
            logger.info(f"Öppnade webbläsare: {url}")
        except Exception as e:
            logger.warning(f"Kunde inte öppna webbläsare: {e}")

    # Run web server and browser opener concurrently
    browser_task = asyncio.create_task(open_browser())
    result = await run_setup_server(port)
    browser_task.cancel()

    return result


def main() -> None:
    """Sets up the vault path, starts signal-cli, and begins listening.

    When pystray is available, a system tray icon is shown with Start/Stop,
    Open Web GUI, and Quit controls.  The watcher loop can be stopped and
    restarted from the tray without quitting the application.

    On macOS the tray event loop must run on the **main thread**, so
    ``tray.run()`` blocks main while the watcher logic runs in a
    background thread spawned by pystray's *setup* callback.
    """
    # Configure logging with console and buffer handlers
    configure_logging()

    logger.info(f"Starting Oden v{__version__}...")

    # Check if this is first run (not configured)
    _is_configured, _config_error = is_configured()
    if not _is_configured:
        logger.info(f"First run detected ({_config_error}) - starting setup wizard...")
        try:
            setup_complete = asyncio.run(run_setup_mode(WEB_PORT))
            if setup_complete:
                logger.info("Setup complete! Reloading configuration...")
                # Reload and get fresh config values
                new_config = reload_config()
                new_number = new_config["signal_number"]
                new_host = new_config["signal_cli_host"]
                new_port = new_config["signal_cli_port"]
                new_unmanaged = new_config["unmanaged_signal_cli"]
                logger.info(
                    "Post-setup config: signal_number=%s, CONFIG_DB=%s",
                    new_number,
                    new_config.get("oden_home", "?") + "/config.db",
                )
                # Persist and apply the configured log level
                log_level_str = new_config.get("log_level_str", "INFO")
                write_log_level(log_level_str)
                apply_log_level(new_config["log_level"])
            else:
                logger.error("Setup was not completed. Exiting.")
                sys.exit(1)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Setup cancelled by user.")
            sys.exit(0)
        except Exception as e:
            logger.exception(f"Error during setup: {e}")
            sys.exit(1)
    else:
        # Use existing config
        new_number = SIGNAL_NUMBER
        new_host = SIGNAL_CLI_HOST
        new_port = SIGNAL_CLI_PORT
        new_unmanaged = UNMANAGED_SIGNAL_CLI

    # Validate configuration
    if new_number == "+46XXXXXXXXX" or not new_number:
        logger.error("❌ Signal number not configured!")
        logger.error("Please run Oden again to complete setup.")
        sys.exit(1)

    # Set up system tray icon
    tray = _create_tray()
    app_state = get_app_state()
    app_state.tray = tray

    signal_manager = None if new_unmanaged else SignalManager(new_host, new_port)

    # --- Tray callbacks use AppState lifecycle helpers ---
    if tray is not None:
        tray.set_callbacks(
            on_quit=app_state.request_quit,
        )

    def _watcher_loop() -> None:
        """Run the async lifecycle (may be called from a background thread)."""
        try:
            asyncio.run(
                _run_lifecycle(
                    host=new_host,
                    port=new_port,
                    signal_manager=signal_manager,
                    tray=tray,
                )
            )
        except (KeyboardInterrupt, SystemExit):
            logger.info("Watcher loop stopped.")
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {e}")
        finally:
            if tray is not None:
                tray.stop()

    if tray is not None:
        # tray.run() blocks main thread (required for macOS NSApp loop).
        # The watcher loop runs in pystray's setup-callback thread.
        tray.run(on_ready=_watcher_loop)
    else:
        # No tray — run the watcher directly on the main thread.
        _watcher_loop()

    sys.exit(0)


def _create_tray() -> OdenTray | None:
    """Create the system tray icon, or return *None* if pystray is unavailable."""
    try:
        from oden.tray import OdenTray

        tray = OdenTray(version=__version__, web_port=WEB_PORT)
        if tray.setup():
            return tray
        return None
    except Exception as e:
        logger.debug("System tray not available: %s", e)
        return None


if __name__ == "__main__":
    main()
