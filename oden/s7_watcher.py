"""
Signal-cli listener and message processor.

Main entry point that connects to signal-cli daemon and processes incoming messages.
First start creates default settings; everything else is configured in the web GUI.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import threading
import webbrowser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oden.tray import OdenTray

from oden import __version__
from oden import config as config_module
from oden.app_state import get_app_state
from oden.config import (
    WEB_ENABLED,
    WEB_PORT,
    bootstrap,
    reload_config,
    signal_config_problem,
)
from oden.dependency_diagnostics import run_startup_dependency_diagnostics
from oden.log_utils import apply_log_level, configure_logging, write_log_level
from oden.signal_listener import subscribe_and_listen
from oden.signal_manager import SignalManager, is_signal_cli_running

logger = logging.getLogger(__name__)


async def _run_lifecycle(
    host: str,
    port: int,
    signal_manager: SignalManager | None,
    tray: OdenTray | None,
    signal_enabled: bool = True,
) -> None:
    """Long-lived async lifecycle that keeps the web server running.

    The signal-cli listener is started/stopped independently via
    asyncio events stored on AppState.  The web server persists
    across stop/start cycles so the GUI is always reachable.
    """
    from oden.signal_log_monitor import monitor_signal_cli_log
    from oden.tak.bridge import start_tak_bridge, stop_tak_bridge
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
    log_monitor_task = None
    if signal_enabled:
        log_monitor_task = asyncio.create_task(monitor_signal_cli_log(quit_event))

    # TAK bridge — no-op unless tak_settings.enabled; runs for the whole lifetime
    await start_tak_bridge()

    try:
        if not signal_enabled:
            # ponytail: choice made at startup; toggling Signal needs an Oden restart
            logger.info("Signal är avstängt — kör utan signal-cli (webb och TAK är igång).")
            await quit_event.wait()

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
        await stop_tak_bridge()

        if log_monitor_task is not None and not log_monitor_task.done():
            log_monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await log_monitor_task

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


def _welcome_first_start(port: int) -> None:
    """Point the operator at the dashboard on the very first start."""
    url = f"http://127.0.0.1:{port}/"
    logger.info("=" * 60)
    logger.info("🛡️  Välkommen till Oden!")
    logger.info("Välj valv under fliken Obsidian och koppla Signal under fliken Signal: %s", url)
    logger.info("=" * 60)

    def _open() -> None:
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning("Kunde inte öppna webbläsare: %s", e)

    # Give the web server a moment to come up in the lifecycle loop.
    timer = threading.Timer(2.0, _open)
    timer.daemon = True
    timer.start()


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
    run_startup_dependency_diagnostics()

    # No wizard: make sure a home directory and config.db exist (creating
    # defaults on first start), then run with whatever is configured. Signal
    # is linked from the Signal tab and the vault chosen in the Obsidian tab.
    try:
        fresh_install = bootstrap()
    except RuntimeError as e:
        logger.error("❌ %s", e)
        sys.exit(1)

    new_config = reload_config()
    if new_config.get("signal_enabled", True):
        problem = signal_config_problem()
        if problem:
            logger.warning("Signal startas inte: %s Oden körs utan Signal tills ett konto är kopplat.", problem)
            config_module.SIGNAL_OFF_REASON = problem
            new_config = reload_config()

    write_log_level(new_config.get("log_level_str", "INFO"))
    apply_log_level(new_config["log_level"])
    new_host = new_config["signal_cli_host"]
    new_port = new_config["signal_cli_port"]
    new_unmanaged = new_config["unmanaged_signal_cli"]
    new_signal_enabled = config_module.SIGNAL_ENABLED

    if fresh_install:
        _welcome_first_start(WEB_PORT)

    # Set up system tray icon
    tray = _create_tray()
    app_state = get_app_state()
    app_state.tray = tray

    signal_manager = None if new_unmanaged or not new_signal_enabled else SignalManager(new_host, new_port)

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
                    signal_enabled=new_signal_enabled,
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
