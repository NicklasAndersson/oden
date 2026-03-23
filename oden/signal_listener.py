"""Signal-cli listener — connects to signal-cli and processes incoming messages."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import logging
import time

from oden import __version__
from oden.app_state import get_app_state
from oden.config import DISPLAY_NAME
from oden.processing import process_message

logger = logging.getLogger(__name__)


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
                "params": {"account": cfg.SIGNAL_NUMBER, "recipient": [cfg.SIGNAL_NUMBER], "message": message},
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
                    "params": {"account": cfg.SIGNAL_NUMBER, "groupId": group_id, "message": message},
                    "id": request_id,
                }
                writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
                await writer.drain()
                logger.info(f"  • Sent to group: {group_name}")

            logger.info(f"Startup message sent to {len(active_groups)} group(s).")

    except Exception as e:
        logger.error(f"ERROR sending startup message: {e}")


async def log_groups(writer: asyncio.StreamWriter) -> list[dict]:
    """Fetches and logs all groups the account is a member of.

    Persists groups to the database so they survive restarts.
    Falls back to the database if the RPC call fails.

    Returns:
        List of group dictionaries (from signal-cli or DB).
    """
    from oden import config as cfg
    from oden.config import CONFIG_DB
    from oden.groups_db import get_all_groups, upsert_groups_bulk

    app_state = get_app_state()

    try:
        response = await app_state.send_jsonrpc(
            "listGroups",
            params={"account": cfg.SIGNAL_NUMBER},
            timeout=10.0,
        )
        if response and "result" in response:
            groups = response["result"]
            # Cache groups in app_state for web GUI access
            app_state.update_groups(groups)

            # Persist to database
            count = upsert_groups_bulk(CONFIG_DB, groups)
            if count:
                logger.debug("Persisted %d groups to database", count)

            if not groups:
                logger.info("No groups found for this account.")
                # Empty RPC result — check if DB has cached groups
                db_groups = get_all_groups(CONFIG_DB)
                if db_groups:
                    logger.info("RPC returned empty, loaded %d group(s) from database cache", len(db_groups))
                    app_state.update_groups(
                        [
                            {
                                "id": g["id"],
                                "name": g["name"],
                                "members": [None] * g["memberCount"],
                                "isMember": g["isMember"],
                            }
                            for g in db_groups
                        ]
                    )
                    return db_groups
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

        # RPC returned no result — fall back to DB
        logger.debug("listGroups returned no result, loading from database")

    except Exception as e:
        logger.warning(f"Could not fetch groups via RPC: {e} — loading from database")

    # Fallback: load from database
    db_groups = get_all_groups(CONFIG_DB)
    if db_groups:
        logger.info("Loaded %d group(s) from database (offline cache)", len(db_groups))
        app_state.update_groups(
            [
                {"id": g["id"], "name": g["name"], "members": [None] * g["memberCount"], "isMember": g["isMember"]}
                for g in db_groups
            ]
        )
    return db_groups


async def update_profile(writer: asyncio.StreamWriter, display_name: str | None) -> None:
    """Sends a JSON-RPC request to update the profile name."""
    from oden import config as cfg

    if not display_name:
        return

    request_id = f"update-profile-{int(time.time())}"
    json_request = {
        "jsonrpc": "2.0",
        "method": "updateProfile",
        "params": {"account": cfg.SIGNAL_NUMBER, "name": display_name},
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


async def _reader_loop(reader: asyncio.StreamReader, app_state: object) -> None:
    """Read lines from the TCP socket and route them via the central dispatcher.

    Runs as a background task so that RPC Futures are resolved while
    other coroutines (log_groups, send_startup_message) are awaiting them.
    """
    while not reader.at_eof():
        line = await reader.readline()
        if not line:
            break

        message_str = line.decode("utf-8").strip()
        if not message_str:
            continue

        try:
            data = json.loads(message_str)
        except json.JSONDecodeError:
            logger.error(f"Received non-JSON message: {message_str}")
            continue

        app_state.dispatch_line(data)


async def subscribe_and_listen(host: str, port: int) -> None:
    """Connects to signal-cli via TCP socket, subscribes to messages, and processes them.

    Runs a single reader loop that dispatches all incoming lines:
    - RPC responses are routed to pending Futures (via app_state.dispatch_line)
    - Receive notifications are queued and processed here

    In multi-account daemon mode, messages include an 'account' field.
    Only messages for the active account (cfg.SIGNAL_NUMBER) are processed.
    """
    from oden import config as cfg

    logger.info(f"Connecting to signal-cli at {host}:{port}...")

    reader = None
    writer = None
    app_state = get_app_state()
    try:
        reader, writer = await asyncio.open_connection(host, port, limit=1024 * 1024 * 100)  # 100 MB limit
        logger.info("Connection successful. Waiting for messages...")

        # Share writer/reader with web server for sending commands
        app_state.writer = writer
        app_state.reader = reader

        # Start the reader/dispatcher loop as a background task so that
        # RPC responses are consumed while we issue startup calls.
        reader_task = asyncio.create_task(_reader_loop(reader, app_state))

        await update_profile(writer, DISPLAY_NAME)
        groups = await log_groups(writer)
        await send_startup_message(writer, groups)

        # Process notifications until the reader loop ends (connection closed)
        try:
            while not reader_task.done():
                try:
                    notification = await asyncio.wait_for(app_state.notification_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                try:
                    params = notification.get("params")
                    if not params:
                        continue

                    # Multi-account mode: extract envelope from nested format
                    msg_data = params
                    if "result" in params and isinstance(params["result"], dict):
                        msg_data = params["result"]

                    # Filter: only process messages for the active account
                    msg_account = msg_data.get("account")
                    if msg_account and msg_account != cfg.SIGNAL_NUMBER:
                        logger.debug(f"Skipping message for non-active account: {msg_account}")
                        continue

                    await process_message(msg_data, reader, writer)
                except Exception as e:
                    logger.error(f"Could not process message.\n  Error: {repr(e)}")
        finally:
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader_task

    except ConnectionRefusedError as e:
        logger.error(f"Connection to signal-cli daemon failed: {e}")
        logger.error("Please ensure signal-cli is running in JSON-RPC mode with a TCP socket.")
        raise
    finally:
        # Clear shared state and cancel any pending RPC futures
        for future in app_state.rpc_pending.values():
            if not future.done():
                future.cancel()
        app_state.rpc_pending.clear()
        app_state.writer = None
        app_state.reader = None
        if writer:
            writer.close()
            await writer.wait_closed()
        logger.info("Connection closed.")
