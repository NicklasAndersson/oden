import asyncio
import datetime
import json
import logging
import os
import re
from typing import Any

from oden import config as cfg
from oden.attachment_handler import save_attachments
from oden.config import CONFIG_DB
from oden.config_db import get_response_by_keyword
from oden.formatting import (
    _format_quote,
    create_fileid,
    find_latest_file_by_fileid,
    format_sender_display,
    get_message_filepath,
    get_safe_group_dir_path,
)
from oden.link_formatter import apply_regex_links
from oden.template_loader import render_append, render_report

logger = logging.getLogger(__name__)

# ==============================================================================
# MESSAGE PROCESSING
# ==============================================================================


def _find_latest_file_for_sender(group_dir: str, source_name: str | None, source_number: str | None) -> str | None:
    """
    Finds the most recent file by a given sender in a group directory.
    Returns the path to the most recent file within APPEND_WINDOW_MINUTES, or None.

    This is a wrapper around find_latest_file_by_fileid from formatting.py.
    """
    return find_latest_file_by_fileid(group_dir, source_name, source_number)


def _apply_regex_links(text: str | None) -> str | None:
    """
    Wrapper function for backward compatibility.
    Use apply_regex_links from link_formatter module instead.
    """
    return apply_regex_links(text)


# Coordinate pattern: optional minus, digits, dot, digits (e.g. 59.514828 or -33.8688)
_COORD = r"(-?\d+\.\d+)"

# Compiled location URL patterns, tried in order.
_LOCATION_PATTERNS: list[re.Pattern[str]] = [
    # Google Maps: maps.google.com/maps?q=LAT%2CLON  or  www.google.com/maps?q=LAT,LON
    re.compile(rf"https://(?:www\.)?(?:maps\.)?google\.com/maps\?q={_COORD}(?:%2[cC]|,){_COORD}"),
    # Apple Maps: maps.apple.com/?q=LAT,LON  or  maps.apple.com/?ll=LAT,LON
    re.compile(rf"https://maps\.apple\.com/\?(?:[^\s]*&)?(?:q|ll)={_COORD},{_COORD}"),
    # OpenStreetMap query params: ?mlat=LAT&mlon=LON
    re.compile(rf"https://(?:www\.)?openstreetmap\.org/?\?(?:[^\s]*&)?mlat={_COORD}&(?:[^\s]*&)?mlon={_COORD}"),
    # OpenStreetMap hash fragment: #map=ZOOM/LAT/LON
    re.compile(rf"https://(?:www\.)?openstreetmap\.org/?[^\s]*#map=[\d.]+/{_COORD}/{_COORD}"),
]


def extract_coordinates(msg: str) -> tuple[str, str] | None:
    """Extract latitude and longitude from a location URL in a message.

    Supports Google Maps, Apple Maps, and OpenStreetMap URLs.

    Args:
        msg: The message text to search for location URLs.

    Returns:
        A (lat, lon) tuple of strings, or None if no location URL is found.
    """
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(msg)
        if match:
            return match.group(1), match.group(2)
    return None


def _extract_message_details(
    envelope: dict[str, Any],
) -> tuple[str | None, str | None, str | None, list[dict[str, Any]]]:
    """
    Helper to extract message content, group title, and group id from an envelope.
    Handles both incoming data messages and outgoing sync messages.
    """
    if "dataMessage" in envelope:
        dm = envelope.get("dataMessage", {})
        group_meta = dm.get("groupV2") or dm.get("group") or dm.get("groupInfo") or {}
        return (
            dm.get("message") or dm.get("body"),
            group_meta.get("name") or group_meta.get("title") or group_meta.get("groupName"),
            group_meta.get("id") or group_meta.get("groupId"),
            dm.get("attachments", []),
        )

    if "syncMessage" in envelope:
        sent = envelope.get("syncMessage", {}).get("sentMessage", {})
        group_info = sent.get("groupInfo", {})
        return (
            sent.get("message"),
            group_info.get("groupName") or group_info.get("title") or group_info.get("name"),
            group_info.get("groupId"),
            sent.get("attachments", []),
        )

    return None, None, None, []


async def _get_attachment_data(
    attachment_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> str | None:
    """
    Wrapper function for backward compatibility.
    Use _get_attachment_data from attachment_handler module instead.
    """
    from attachment_handler import _get_attachment_data as get_attachment_data_impl

    return await get_attachment_data_impl(attachment_id, reader, writer)


async def _save_attachments(
    attachments: list[dict[str, Any]],
    group_dir: str,
    dt: datetime.datetime,
    source_name: str | None,
    source_number: str | None,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> list[str]:
    """
    Wrapper function for backward compatibility.
    Use save_attachments from attachment_handler module instead.
    """
    return await save_attachments(attachments, group_dir, dt, source_name, source_number, reader, writer)


async def _send_reply(group_id: str, message: str, writer: asyncio.StreamWriter) -> None:
    """Sends a reply message to a given group ID via signal-cli JSON-RPC."""
    request_id = f"send-{datetime.datetime.now().microsecond}"
    json_request = {
        "jsonrpc": "2.0",
        "method": "send",
        "params": {"groupId": group_id, "message": message},
        "id": request_id,
    }
    request_str = json.dumps(json_request) + "\n"

    try:
        writer.write(request_str.encode("utf-8"))
        await writer.drain()
        logger.info(f"Sent reply to {group_id}")
    except Exception as e:
        logger.error(f"ERROR sending reply to {group_id}: {e}")


async def process_message(obj: dict[str, Any], reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """
    Parses a signal message object and writes it to a markdown file, including attachments.
    If a file for that sender already exists from the same minute, appends the new message.
    """
    envelope = obj.get("envelope", {})
    if not envelope:
        return

    msg, group_title, group_id, attachments = _extract_message_details(envelope)

    # Whitelist has priority: if set, only allow whitelisted groups
    if cfg.WHITELIST_GROUPS:
        if group_title and group_title not in cfg.WHITELIST_GROUPS:
            logger.info(f"Skipping message: group '{group_title}' not in whitelist")
            return
    elif group_title and group_title in cfg.IGNORED_GROUPS:
        logger.info(f"Skipping message from ignored group: {group_title}")
        return

    # If message starts with '--', ignore it.
    if msg and msg.strip().startswith("--"):
        logger.info("Skipping message: Starts with '--'.")
        return

    source_name = envelope.get("sourceName")
    source_number = envelope.get("sourceNumber") or envelope.get("source")
    dm = envelope.get("dataMessage", {})
    quote = dm.get("quote")
    now = datetime.datetime.now(cfg.TIMEZONE)

    # --- Append Logic ---
    is_plus_plus_append = cfg.PLUS_PLUS_ENABLED and msg and msg.strip().startswith("++")
    is_reply_append = False
    if quote:
        quote_ts = quote.get("id", 0)
        quote_dt = datetime.datetime.fromtimestamp(quote_ts / 1000.0, tz=cfg.TIMEZONE)
        if (now - quote_dt) < datetime.timedelta(minutes=cfg.APPEND_WINDOW_MINUTES):
            is_reply_append = True

    if is_plus_plus_append or is_reply_append:
        if not group_title:
            logger.error("Cannot append message, missing group.")
            return

        group_dir = get_safe_group_dir_path(group_title)

        # Determine whose file to append to
        if is_reply_append:
            # For replies, find the file of the *quoted author*
            append_target_number = quote.get("author")
            append_target_name = None  # Name isn't available in the quote object
            if not append_target_number:
                logger.error("Cannot append reply, quote author number is missing.")
                return
        else:
            # For '++', find the file of the *current sender*
            append_target_number = source_number
            append_target_name = source_name

        if not (append_target_name or append_target_number):
            logger.error("Cannot append message, missing target user details.")
            return

        latest_file = _find_latest_file_for_sender(group_dir, append_target_name, append_target_number)

        if latest_file:
            new_text = ""
            if msg:
                new_text = msg.strip().removeprefix("++").strip() if is_plus_plus_append else msg.strip()

            attachment_links = []
            if attachments:
                original_group_dir = os.path.dirname(latest_file)
                attachment_links = await _save_attachments(
                    attachments, original_group_dir, now, source_name, source_number, reader, writer
                )

            # Only append if there's actual content (text or attachments)
            if new_text or attachment_links:
                sender_display = format_sender_display(source_name, source_number)
                linked_text = _apply_regex_links(new_text) if new_text else None

                # Extract location coordinates from the message
                append_lat, append_lon = None, None
                if msg:
                    append_coords = extract_coordinates(msg)
                    if append_coords:
                        append_lat, append_lon = append_coords

                append_content = render_append(
                    tnr=now.strftime("%d%H%M"),
                    timestamp_iso=now.isoformat(),
                    sender_display=sender_display,
                    message=linked_text,
                    attachments=attachment_links or None,
                    lat=append_lat,
                    lon=append_lon,
                )

                try:
                    with open(latest_file, "a", encoding="utf-8") as f:
                        f.write(append_content)
                    logger.info(f"APPENDED (reply or ++) TO: {latest_file}")
                except OSError as e:
                    logger.error(f"Failed to append to file {latest_file}: {e}")
            else:
                logger.info("Ignoring empty append message.")

        else:
            logger.info("APPEND FAILED: No recent file found for sender.")
            if is_reply_append:
                # If reply-append fails, it should be treated as a new message,
                # but with the quote intact.
                quote = dm.get("quote")
            else:
                # If ++ append fails, we just process it as a new message without the ++
                if msg:
                    msg = msg.strip().removeprefix("++").strip()

        # If the append was successful (or a ++ which always consumes the message), we are done.
        # If a reply-append fails, we continue on to process it as a new message.
        if is_plus_plus_append or (is_reply_append and latest_file):
            return

    # --- Handle Standard Commands (#) ---
    if msg and msg.strip().startswith("#"):
        command = msg.strip()[1:].lower()
        if not command:
            return
        response_text = get_response_by_keyword(CONFIG_DB, command)
        if response_text:
            try:
                await _send_reply(group_id, response_text, writer)
                logger.info(f"Sent '{command}' response.")
            except Exception as e:
                logger.error(f"Could not process #{command} command: {e}")
        else:
            logger.info(f"No response found for command: #{command}")
        return

    # If no message body and no attachments, skip.
    if not msg and not attachments:
        logger.info("Skipping message: No message body and no attachments.")
        return

    if not group_title:
        logger.info("Skipping message: Not a group message.")
        return

    dt = (
        datetime.datetime.fromtimestamp(envelope.get("timestamp") / 1000.0, tz=cfg.TIMEZONE)
        if envelope.get("timestamp")
        else now
    )

    path = get_message_filepath(group_title, dt, source_name, source_number, unique=True)
    group_dir = os.path.dirname(path)
    os.makedirs(group_dir, exist_ok=True)

    # Generate fileid for frontmatter (consistent identification across filename formats)
    fileid = create_fileid(dt, source_name, source_number)

    lat, lon = None, None
    if msg:
        coords = extract_coordinates(msg)
        if coords:
            lat, lon = coords

    attachment_links = await _save_attachments(attachments, group_dir, dt, source_name, source_number, reader, writer)

    # --- Prepare content for Markdown file using template ---
    sender_display = format_sender_display(source_name, source_number)

    # Format quote block if present
    quote_formatted = None
    if quote:
        quote_lines = _format_quote(quote)
        quote_formatted = "\n".join(quote_lines)

    # Apply regex links to message
    linked_msg = _apply_regex_links(msg.strip()) if msg else None

    content = render_report(
        fileid=fileid,
        group_title=group_title,
        group_id=group_id,
        tnr=dt.strftime("%d%H%M"),
        timestamp_iso=dt.isoformat(),
        sender_display=sender_display,
        sender_name=source_name,
        sender_number=source_number,
        lat=lat,
        lon=lon,
        quote_formatted=quote_formatted,
        message=linked_msg,
        attachments=attachment_links or None,
    )

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"WROTE: {path}")
    except OSError as e:
        logger.error(f"Failed to write file {path}: {e}")
