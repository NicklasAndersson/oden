"""
Signal-cli listener and message processor.

Main entry point that connects to signal-cli daemon and processes incoming messages.
Supports first-run setup wizard for initial configuration.
"""

import asyncio
import datetime
import json
import logging
import sys
import time
import webbrowser

from oden import __version__
from oden.app_state import get_app_state
from oden.config import (
    DISPLAY_NAME,
    LOG_FILE,
    LOG_LEVEL,
    SIGNAL_CLI_HOST,
    SIGNAL_CLI_PORT,
    SIGNAL_NUMBER,
    UNMANAGED_SIGNAL_CLI,
    WEB_ENABLED,
    WEB_PORT,
    is_configured,
    reload_config,
)
from oden.log_buffer import get_log_buffer
from oden.processing import process_message
from oden.signal_manager import SignalManager, is_signal_cli_running

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure logging with console output, file output, and in-memory buffer."""
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation (5MB max, keep 3 backups)
    if LOG_FILE:
        try:
            log_path = Path(LOG_FILE).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            file_handler.setLevel(LOG_LEVEL)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            root_logger.info(f"Logging to file: {log_path}")
        except Exception as e:
            root_logger.warning(f"Could not set up file logging: {e}")

    # In-memory log buffer for web GUI
    log_buffer = get_log_buffer()
    log_buffer.setLevel(LOG_LEVEL)
    root_logger.addHandler(log_buffer)


async def send_startup_message(writer: asyncio.StreamWriter, groups: list[dict] | None = None) -> None:
    """Sends a startup notification message based on STARTUP_MESSAGE config.

    Reads config values dynamically to support live reload after setup.

    Args:
        writer: The asyncio StreamWriter for sending messages.
        groups: List of group dictionaries from listGroups (required if mode is 'all').
    """
    # Import config values dynamically to get post-reload values
    from oden import config as cfg

    if cfg.STARTUP_MESSAGE == "off":
        logger.info("Startup message disabled (startup_message=off)")
        return

    now = datetime.datetime.now(cfg.TIMEZONE)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    message = f"🚀 Oden v{__version__} started\n📅 {timestamp}"

    try:
        if cfg.STARTUP_MESSAGE == "self":
            # Send to self only
            request_id = f"startup-{int(time.time())}"
            json_request = {
                "jsonrpc": "2.0",
                "method": "send",
                "params": {"recipient": [cfg.SIGNAL_NUMBER], "message": message},
                "id": request_id,
            }
            logger.info(f"Sending startup message to {cfg.SIGNAL_NUMBER}...")
            writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
            await writer.drain()
            logger.info("Startup message sent to self.")

        elif cfg.STARTUP_MESSAGE == "all":
            if not groups:
                logger.warning("No groups available for startup message (startup_message=all)")
                return

            # Filter out ignored groups
            active_groups = [g for g in groups if g.get("name") not in cfg.IGNORED_GROUPS]
            if not active_groups:
                logger.info("No active groups to send startup message to (all groups ignored)")
                return
                return

            logger.info(f"Sending startup message to {len(active_groups)} group(s)...")
            for group in active_groups:
                group_id = group.get("id")
                group_name = group.get("name", "Unknown")
                if not group_id:
                    continue

                request_id = f"startup-{group_id}-{int(time.time())}"
                json_request = {
                    "jsonrpc": "2.0",
                    "method": "send",
                    "params": {"groupId": group_id, "message": message},
                    "id": request_id,
                }
                writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
                await writer.drain()
                logger.info(f"  • Sent to group: {group_name}")

            logger.info(f"Startup message sent to {len(active_groups)} group(s).")

    except Exception as e:
        logger.error(f"ERROR sending startup message: {e}")


async def log_groups(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> list[dict]:
    """Fetches and logs all groups the account is a member of.

    Reads config values dynamically to support live reload.

    Returns:
        List of group dictionaries from signal-cli.
    """
    from oden import config as cfg

    app_state = get_app_state()
    request_id = f"list-groups-{int(time.time())}"
    json_request = {
        "jsonrpc": "2.0",
        "method": "listGroups",
        "id": request_id,
    }
    request_str = json.dumps(json_request) + "\n"

    try:
        writer.write(request_str.encode("utf-8"))
        await writer.drain()

        # Wait for response with timeout
        response_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
        if not response_line:
            logger.warning("No response received for listGroups request")
            return []

        response = json.loads(response_line.decode("utf-8"))
        if response.get("id") == request_id and "result" in response:
            groups = response["result"]
            # Cache groups in app_state for web GUI access
            app_state.update_groups(groups)

            if not groups:
                logger.info("No groups found for this account.")
                return []

            logger.info(f"Account is member of {len(groups)} group(s):")
            for group in groups:
                group_name = group.get("name", "Unknown")
                is_ignored = group_name in cfg.IGNORED_GROUPS
                status = " (IGNORED)" if is_ignored else ""
                logger.info(f"  • {group_name}{status}")

            if cfg.IGNORED_GROUPS:
                ignored_count = sum(1 for g in groups if g.get("name") in cfg.IGNORED_GROUPS)
                logger.info(f"Ignored groups configured: {len(cfg.IGNORED_GROUPS)}, matched: {ignored_count}")

            return groups
        else:
            logger.debug(f"Unexpected response for listGroups: {response}")
            return []

    except asyncio.TimeoutError:
        logger.warning("Timeout waiting for listGroups response")
        return []
    except Exception as e:
        logger.error(f"ERROR fetching groups: {e}")
        return []


async def update_profile(writer: asyncio.StreamWriter, display_name: str | None) -> None:
    """Sends a JSON-RPC request to update the profile name."""
    if not display_name:
        return

    request_id = f"update-profile-{int(time.time())}"
    json_request = {
        "jsonrpc": "2.0",
        "method": "updateProfile",
        "params": {"name": display_name},
        "id": request_id,
    }
    request_str = json.dumps(json_request) + "\n"

    try:
        logger.info(f"Attempting to update profile name to '{display_name}'...")
        writer.write(request_str.encode("utf-8"))
        await writer.drain()
        # Note: We are not waiting for a response here to avoid blocking.
        # The update is "fire and forget".
        logger.info("Profile name update request sent.")
    except Exception as e:
        logger.error(f"ERROR sending updateProfile request: {e}")


async def subscribe_and_listen(host: str, port: int) -> None:
    """Connects to signal-cli via TCP socket, subscribes to messages, and processes them."""
    logger.info(f"Connecting to signal-cli at {host}:{port}...")

    reader = None
    writer = None
    app_state = get_app_state()
    try:
        reader, writer = await asyncio.open_connection(host, port, limit=1024 * 1024 * 100)  # 100 MB limit
        logger.info("Connection successful. Waiting for messages...")

        # Share writer with web server for sending commands
        app_state.writer = writer
        app_state.reader = reader

        await update_profile(writer, DISPLAY_NAME)
        groups = await log_groups(reader, writer)
        await send_startup_message(writer, groups)

        while not reader.at_eof():
            line = await reader.readline()
            if not line:
                break

            message_str = line.decode("utf-8").strip()
            if not message_str:
                continue

            try:
                data = json.loads(message_str)
                if data.get("method") == "receive" and (params := data.get("params")):
                    await process_message(params, reader, writer)
                else:
                    # Log other responses if they are not the response to our updateProfile request
                    if not (isinstance(data, dict) and data.get("id", "").startswith("update-profile-")):
                        logger.debug(f"Received non-message data: {data}")
            except json.JSONDecodeError:
                logger.error(f"Received non-JSON message: {message_str}")
            except Exception as e:
                logger.error(f"Could not process message.\n  Error: {repr(e)}\n  Message: {message_str}")

    except ConnectionRefusedError as e:
        logger.error(f"Connection to signal-cli daemon failed: {e}")
        logger.error("Please ensure signal-cli is running in JSON-RPC mode with a TCP socket.")
        raise
    finally:
        # Clear shared state
        app_state.writer = None
        app_state.reader = None
        if writer:
            writer.close()
            await writer.wait_closed()
        logger.info("Connection closed.")


async def run_all(host: str, port: int) -> None:
    """Run signal-cli listener and optionally web server concurrently."""
    tasks = [subscribe_and_listen(host, port)]

    if WEB_ENABLED:
        from oden.web_server import run_web_server

        tasks.append(run_web_server(WEB_PORT))
        logger.info(f"Web GUI enabled on port {WEB_PORT}")

    await asyncio.gather(*tasks)


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
    """Sets up the vault path, starts signal-cli, and begins listening."""
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

    if new_unmanaged:
        if not is_signal_cli_running(new_host, new_port):
            logger.error("signal-cli is not running. Please start it manually.")
            sys.exit(1)
        logger.info("Running in unmanaged mode. Assuming signal-cli is already running.")
        try:
            asyncio.run(run_all(new_host, new_port))
        except (KeyboardInterrupt, SystemExit):
            logger.info("Exiting on user request.")
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {e}")
        sys.exit(0)
    else:
        signal_manager = SignalManager(new_number, new_host, new_port)
        try:
            signal_manager.start()
            asyncio.run(run_all(new_host, new_port))
        except (KeyboardInterrupt, SystemExit):
            logger.info("Exiting on user request.")
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {e}")
        finally:
            signal_manager.stop()
            logger.info("Oden shut down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
