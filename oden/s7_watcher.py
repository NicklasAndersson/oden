"""
Signal-cli listener and message processor.

Main entry point that connects to signal-cli daemon and processes incoming messages.
"""
import sys
import json
import asyncio
import logging
import time
from typing import Optional

from oden.config import (
    SIGNAL_NUMBER, 
    DISPLAY_NAME,
    SIGNAL_CLI_HOST, 
    SIGNAL_CLI_PORT,
    UNMANAGED_SIGNAL_CLI,
    LOG_LEVEL
)
from oden.signal_manager import SignalManager, is_signal_cli_running
from oden.processing import process_message

logger = logging.getLogger(__name__)


async def update_profile(writer: asyncio.StreamWriter, display_name: Optional[str]) -> None:
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
        writer.write(request_str.encode('utf-8'))
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
    try:
        reader, writer = await asyncio.open_connection(host, port, limit=1024 * 1024 * 100) # 100 MB limit
        logger.info("Connection successful. Waiting for messages...")

        await update_profile(writer, DISPLAY_NAME)
        
        while not reader.at_eof():
            line = await reader.readline()
            if not line:
                break
            
            message_str = line.decode('utf-8').strip()
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
        sys.exit(1)
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        logger.info("Connection closed.")


def main() -> None:
    """Sets up the vault path, starts signal-cli, and begins listening."""
    # Configure logging
    logging.basicConfig(
        level=LOG_LEVEL,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
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
            asyncio.run(subscribe_and_listen(SIGNAL_CLI_HOST, SIGNAL_CLI_PORT))
        except (KeyboardInterrupt, SystemExit):
            logger.info("Exiting on user request.")
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {e}")
        sys.exit(0)
    else:
        signal_manager = SignalManager(SIGNAL_NUMBER, SIGNAL_CLI_HOST, SIGNAL_CLI_PORT)
        try:
            signal_manager.start()
            asyncio.run(subscribe_and_listen(SIGNAL_CLI_HOST, SIGNAL_CLI_PORT))
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
