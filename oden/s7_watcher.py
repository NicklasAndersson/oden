"""
Signal-cli listener and message processor.

Main entry point that connects to signal-cli daemon and processes incoming messages.
"""

import asyncio
import datetime
import json
import logging
import sys
import time

from oden import __version__
from oden.app_state import get_app_state
from oden.config import (
    DISPLAY_NAME,
    IGNORED_GROUPS,
    LOG_LEVEL,
    SIGNAL_CLI_HOST,
    SIGNAL_CLI_PORT,
    SIGNAL_NUMBER,
    STARTUP_MESSAGE,
    TIMEZONE,
    UNMANAGED_SIGNAL_CLI,
    WEB_ENABLED,
    WEB_PORT,
)
from oden.log_buffer import get_log_buffer
from oden.processing import process_message
from oden.signal_manager import SignalManager, is_signal_cli_running

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure logging with both console output and in-memory buffer."""
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root_logger.addHandler(console_handler)

    # In-memory log buffer for web GUI
    log_buffer = get_log_buffer()
    log_buffer.setLevel(LOG_LEVEL)
    root_logger.addHandler(log_buffer)


async def send_startup_message(writer: asyncio.StreamWriter, groups: list[dict] | None = None) -> None:
    """Sends a startup notification message based on STARTUP_MESSAGE config.
    
    Args:
        writer: The asyncio StreamWriter for sending messages.
        groups: List of group dictionaries from listGroups (required if mode is 'all').
    """
    if STARTUP_MESSAGE == "off":
        logger.info("Startup message disabled (startup_message=off)")
        return

    now = datetime.datetime.now(TIMEZONE)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    message = f"🚀 Oden v{__version__} started\n📅 {timestamp}"

    try:
        if STARTUP_MESSAGE == "self":
            # Send to self only
            request_id = f"startup-{int(time.time())}"
            json_request = {
                "jsonrpc": "2.0",
                "method": "send",
                "params": {"recipient": [SIGNAL_NUMBER], "message": message},
                "id": request_id,
            }
            logger.info(f"Sending startup message to {SIGNAL_NUMBER}...")
            writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
            await writer.drain()
            logger.info("Startup message sent to self.")

        elif STARTUP_MESSAGE == "all":
            if not groups:
                logger.warning("No groups available for startup message (startup_message=all)")
                return

            # Filter out ignored groups
            active_groups = [g for g in groups if g.get("name") not in IGNORED_GROUPS]
            if not active_groups:
                logger.info("No active groups to send startup message to (all groups ignored)")
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
    
    Returns:
        List of group dictionaries from signal-cli.
    """
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
            if not groups:
                logger.info("No groups found for this account.")
                return []

            logger.info(f"Account is member of {len(groups)} group(s):")
            for group in groups:
                group_name = group.get("name", "Unknown")
                is_ignored = group_name in IGNORED_GROUPS
                status = " (IGNORED)" if is_ignored else ""
                logger.info(f"  • {group_name}{status}")

            if IGNORED_GROUPS:
                ignored_count = sum(1 for g in groups if g.get("name") in IGNORED_GROUPS)
                logger.info(f"Ignored groups configured: {len(IGNORED_GROUPS)}, matched: {ignored_count}")

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


def main() -> None:
    """Sets up the vault path, starts signal-cli, and begins listening."""
    # Configure logging with console and buffer handlers
    configure_logging()

    logger.info("Starting s7_watcher...")

    if SIGNAL_NUMBER == "YOUR_SIGNAL_NUMBER":
        logger.error("❌ Signal number not configured!")
        logger.error("Please update 'number' in config.ini with your Signal phone number")
        logger.error("Example: number = +46701234567")
        sys.exit(1)

    if UNMANAGED_SIGNAL_CLI:
        if not is_signal_cli_running(SIGNAL_CLI_HOST, SIGNAL_CLI_PORT):
            logger.error("signal-cli is not running. Please start it manually.")
            sys.exit(1)
        logger.info("Running in unmanaged mode. Assuming signal-cli is already running.")
        try:
            asyncio.run(run_all(SIGNAL_CLI_HOST, SIGNAL_CLI_PORT))
        except (KeyboardInterrupt, SystemExit):
            logger.info("Exiting on user request.")
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {e}")
        sys.exit(0)
    else:
        signal_manager = SignalManager(SIGNAL_NUMBER, SIGNAL_CLI_HOST, SIGNAL_CLI_PORT)
        try:
            signal_manager.start()
            asyncio.run(run_all(SIGNAL_CLI_HOST, SIGNAL_CLI_PORT))
        except (KeyboardInterrupt, SystemExit):
            logger.info("Exiting on user request.")
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {e}")
        finally:
            signal_manager.stop()
            logger.info("s7_watcher shut down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
