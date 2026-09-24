import asyncio
import contextlib
import datetime
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from oden import config as cfg
from oden.attachment_handler import save_attachments
from oden.formatting import (
    _format_quote,
    create_fileid,
    find_latest_file_by_fileid,
    format_sender_display,
    get_message_filepath,
    get_safe_group_dir_path,
)
from oden.groups_db import upsert_group
from oden.responses_db import get_response_by_keyword
from oden.template_loader import render_append, render_report

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessOutcome:
    """What the fallback flow did with a message, for the Flöde view.

    ``action`` is one of ``wrote``, ``appended``, ``command``, ``skipped`` or ``error``.
    """

    action: str
    reason: str
    path: str | None = None


# ==============================================================================
# SIGNAL CONFIRMATION HELPERS
# ==============================================================================


async def _send_reaction(source_number: str | None, timestamp: int, group_id: str | None) -> None:
    """Send an emoji reaction to confirm a saved message."""
    # ponytail: "tak:" senders are synthetic CoT sources, not Signal recipients
    if not cfg.AUTO_REACTION_ENABLED or not source_number or source_number.startswith("tak:"):
        return
    try:
        from oden.app_state import get_app_state

        params: dict[str, Any] = {
            "account": cfg.SIGNAL_NUMBER,
            "emoji": cfg.AUTO_REACTION_EMOJI,
            "targetAuthor": source_number,
            "targetTimestamp": timestamp,
        }
        if group_id:
            params["groupId"] = [group_id]
        else:
            params["recipient"] = [source_number]
        result = await get_app_state().send_jsonrpc("sendReaction", params=params)
        if result is not None:
            logger.debug("Sent reaction to %s", source_number)
        else:
            logger.debug("Reaction to %s got no response", source_number)
    except Exception as e:
        logger.warning("Failed to send reaction: %s", e)


async def _send_read_receipt(source_number: str | None, timestamp: int) -> None:
    """Send a read receipt to confirm a processed message."""
    if not cfg.AUTO_READ_RECEIPT_ENABLED or not source_number or source_number.startswith("tak:"):
        return
    try:
        from oden.app_state import get_app_state

        result = await get_app_state().send_jsonrpc(
            "sendReceipt",
            params={
                "account": cfg.SIGNAL_NUMBER,
                "recipient": source_number,
                "targetTimestamp": [timestamp],
                "type": "read",
            },
        )
        if result is not None:
            logger.debug("Sent read receipt to %s", source_number)
        else:
            logger.debug("Read receipt to %s got no response", source_number)
    except Exception as e:
        logger.warning("Failed to send read receipt: %s", e)


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

    return await get_attachment_data_impl(attachment_id)


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
    return await save_attachments(attachments, group_dir, dt, source_name, source_number)


async def _send_reply(group_id: str, message: str, writer: asyncio.StreamWriter) -> None:
    """Sends a reply message to a given group ID via signal-cli JSON-RPC."""
    request_id = f"send-{datetime.datetime.now().microsecond}"
    json_request = {
        "jsonrpc": "2.0",
        "method": "send",
        "params": {"account": cfg.SIGNAL_NUMBER, "groupId": group_id, "message": message},
        "id": request_id,
    }
    request_str = json.dumps(json_request) + "\n"

    try:
        writer.write(request_str.encode("utf-8"))
        await writer.drain()
        logger.info(f"Sent reply to {group_id}")
    except Exception as e:
        logger.error(f"ERROR sending reply to {group_id}: {e}")


async def process_message(
    obj: dict[str, Any], reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> ProcessOutcome:
    """
    Parses a signal message object and writes it to a markdown file, including attachments.
    If a file for that sender already exists from the same minute, appends the new message.
    """
    envelope = obj.get("envelope", {})
    if not envelope:
        return ProcessOutcome("skipped", "Tomt kuvert")

    # Skip syncMessages — these are our own outgoing messages echoed back by signal-cli
    if "syncMessage" in envelope and "dataMessage" not in envelope:
        logger.debug("Skipping sync message (own outgoing message)")
        return ProcessOutcome("skipped", "Eget utgående meddelande (sync) sparas inte")

    msg, group_title, group_id, attachments = _extract_message_details(envelope)

    # Track group in database so it persists across restarts
    if group_title and group_id:
        with contextlib.suppress(Exception):
            upsert_group(cfg.CONFIG_DB, group_id, group_title, account=cfg.SIGNAL_NUMBER)

    # If message starts with '--', ignore it.
    if msg and msg.strip().startswith("--"):
        logger.info("Skipping message: Starts with '--'.")
        return ProcessOutcome("skipped", "Börjar med '--' och ska inte sparas")

    source_name = envelope.get("sourceName")
    source_number = envelope.get("sourceNumber") or envelope.get("source")

    # Resolve name via contact cache if envelope sourceName is missing or matches number
    from oden.app_state import get_app_state

    source_name = get_app_state().resolve_contact_name(source_number, source_name)

    dm = envelope.get("dataMessage", {})
    quote = dm.get("quote")
    now = datetime.datetime.now(cfg.TIMEZONE)

    # --- Append Logic (reply only) ---
    is_reply_append = False
    if quote:
        quote_ts = quote.get("id", 0)
        quote_dt = datetime.datetime.fromtimestamp(quote_ts / 1000.0, tz=cfg.TIMEZONE)
        if (now - quote_dt) < datetime.timedelta(minutes=cfg.APPEND_WINDOW_MINUTES):
            is_reply_append = True

    if is_reply_append:
        if not group_title:
            logger.error("Cannot append message, missing group.")
            return ProcessOutcome("skipped", "Citerat svar utan grupp kan inte läggas till någon fil")

        group_dir = get_safe_group_dir_path(group_title)

        # For replies, find the file of the quoted author.
        append_target_number = quote.get("author")
        append_target_name = None  # Name isn't available in the quote object
        if not append_target_number:
            logger.error("Cannot append reply, quote author number is missing.")
            return ProcessOutcome("skipped", "Citerat svar saknar författare")

        if not (append_target_name or append_target_number):
            logger.error("Cannot append message, missing target user details.")
            return ProcessOutcome("skipped", "Citerat svar saknar författare")

        latest_file = _find_latest_file_for_sender(group_dir, append_target_name, append_target_number)
        append_succeeded = False
        append_outcome = ProcessOutcome("skipped", "Tomt svar – inget att lägga till")

        if latest_file:
            new_text = ""
            if msg:
                new_text = msg.strip()

            attachment_links = []
            if attachments:
                original_group_dir = os.path.dirname(latest_file)
                attachment_links = await _save_attachments(
                    attachments, original_group_dir, now, source_name, source_number, reader, writer
                )

            # Only append if there's actual content (text or attachments)
            if new_text or attachment_links:
                sender_display = format_sender_display(source_name, source_number)
                linked_text = new_text or None

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
                    logger.info(f"APPENDED (reply) TO: {latest_file}")
                    append_succeeded = True
                    append_outcome = ProcessOutcome(
                        "appended",
                        f"Citerat svar inom {cfg.APPEND_WINDOW_MINUTES} min lades till i den citerade avsändarens fil",
                        latest_file,
                    )
                    # Fire-and-forget confirmations
                    msg_ts = envelope.get("timestamp")
                    if msg_ts:
                        asyncio.create_task(_send_reaction(source_number, msg_ts, group_id))
                        asyncio.create_task(_send_read_receipt(source_number, msg_ts))
                except OSError as e:
                    logger.error(f"Failed to append to file {latest_file}: {e}")
            else:
                logger.info("Ignoring empty append message.")
                append_succeeded = True

        else:
            logger.info("APPEND FAILED: No recent file found for sender.")

        if not append_succeeded:
            # If reply-append fails, treat as a new message with quote intact.
            quote = dm.get("quote")

        # If the append was successful (or an empty append was intentionally consumed), we are done.
        # If the append failed, we continue on to process it as a new message.
        if append_succeeded:
            return append_outcome

    # --- Handle Standard Commands (#) ---
    if msg and msg.strip().startswith("#"):
        command = msg.strip()[1:].lower()
        if not command:
            return ProcessOutcome("skipped", "Tomt kommando ('#')")
        response_text = get_response_by_keyword(cfg.CONFIG_DB, command)
        if response_text:
            try:
                await _send_reply(group_id, response_text, writer)
                logger.info(f"Sent '{command}' response.")
            except Exception as e:
                logger.error(f"Could not process #{command} command: {e}")
        else:
            logger.info(f"No response found for command: #{command}")
            return ProcessOutcome("command", f"Kommandot #{command} saknar svar i Svar och kommandon")
        return ProcessOutcome("command", f"Kommandot #{command} besvarades i chatten")

    # If no message body and no attachments, skip.
    if not msg and not attachments:
        logger.info("Skipping message: No message body and no attachments.")
        return ProcessOutcome("skipped", "Varken text eller bilagor")

    if not group_title:
        logger.info("Skipping message: Not a group message.")
        return ProcessOutcome("skipped", "Direktmeddelanden sparas inte, bara gruppmeddelanden")

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

    linked_msg = msg.strip() if msg else None

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
        # Fire-and-forget confirmations
        msg_ts = envelope.get("timestamp")
        if msg_ts:
            asyncio.create_task(_send_reaction(source_number, msg_ts, group_id))
            asyncio.create_task(_send_read_receipt(source_number, msg_ts))
    except OSError as e:
        logger.error(f"Failed to write file {path}: {e}")
        return ProcessOutcome("error", f"Kunde inte skriva filen: {e}", path)
    return ProcessOutcome("wrote", "Nytt meddelande sparades som egen fil", path)


def preview_message(obj: dict[str, Any]) -> tuple[ProcessOutcome, str | None]:
    """What :func:`process_message` would do, for the Testruta.

    Same decisions in the same order, but nothing is written, sent, created or
    stored. Returns the outcome and, for a new file, the rendered content.
    """
    result = _preview(obj)
    return result if isinstance(result, tuple) else (result, None)


def _preview(obj: dict[str, Any]) -> ProcessOutcome | tuple[ProcessOutcome, str]:
    envelope = obj.get("envelope", {})
    if not envelope:
        return ProcessOutcome("skipped", "Tomt kuvert")
    if "syncMessage" in envelope and "dataMessage" not in envelope:
        return ProcessOutcome("skipped", "Eget utgående meddelande (sync) sparas inte")

    msg, group_title, group_id, attachments = _extract_message_details(envelope)
    if msg and msg.strip().startswith("--"):
        return ProcessOutcome("skipped", "Börjar med '--' och ska inte sparas")

    source_name = envelope.get("sourceName")
    source_number = envelope.get("sourceNumber") or envelope.get("source")
    quote = (envelope.get("dataMessage") or {}).get("quote")
    if quote:
        return ProcessOutcome(
            "skipped",
            "Citerat svar – läggs till i en befintlig fil inom tidsfönstret, annars som nytt meddelande (testas inte här)",
        )

    if msg and msg.strip().startswith("#"):
        command = msg.strip()[1:].lower()
        if not command:
            return ProcessOutcome("skipped", "Tomt kommando ('#')")
        if get_response_by_keyword(cfg.CONFIG_DB, command):
            return ProcessOutcome("command", f"Kommandot #{command} skulle besvaras i chatten")
        return ProcessOutcome("command", f"Kommandot #{command} saknar svar i Svar och kommandon")

    if not msg and not attachments:
        return ProcessOutcome("skipped", "Varken text eller bilagor")
    if not group_title:
        return ProcessOutcome("skipped", "Direktmeddelanden sparas inte, bara gruppmeddelanden")

    dt = (
        datetime.datetime.fromtimestamp(envelope.get("timestamp") / 1000.0, tz=cfg.TIMEZONE)
        if envelope.get("timestamp")
        else datetime.datetime.now(cfg.TIMEZONE)
    )
    path = get_message_filepath(group_title, dt, source_name, source_number, unique=True)
    coords = extract_coordinates(msg) if msg else None
    content = render_report(
        fileid=create_fileid(dt, source_name, source_number),
        group_title=group_title,
        group_id=group_id,
        tnr=dt.strftime("%d%H%M"),
        timestamp_iso=dt.isoformat(),
        sender_display=format_sender_display(source_name, source_number),
        sender_name=source_name,
        sender_number=source_number,
        lat=coords[0] if coords else None,
        lon=coords[1] if coords else None,
        quote_formatted=None,
        message=msg.strip() if msg else None,
        attachments=None,
    )
    return ProcessOutcome("wrote", "Nytt meddelande skulle sparas som egen fil", path), content
