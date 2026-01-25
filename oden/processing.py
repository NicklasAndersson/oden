import asyncio
import datetime
import json
import logging
import os
import re
from typing import Any

from oden.attachment_handler import save_attachments
from oden.config import APPEND_WINDOW_MINUTES, IGNORED_GROUPS, PLUS_PLUS_ENABLED, TIMEZONE
from oden.formatting import (
    _format_quote,
    format_sender_display,
    get_message_filepath,
    get_safe_group_dir_path,
)
from oden.link_formatter import apply_regex_links

logger = logging.getLogger(__name__)

# ==============================================================================
# MESSAGE PROCESSING
# ==============================================================================


def _find_latest_file_for_sender(group_dir: str, source_name: str | None, source_number: str | None) -> str | None:
    """
    Finds the most recent file by a given sender in a group directory.
    Returns the path to the most recent file within APPEND_WINDOW_MINUTES, or None.
    """
    latest_file = None
    latest_time = datetime.datetime.min.replace(tzinfo=TIMEZONE)

    # Construct sender identifier for matching filenames
    sender_id_parts = []
    if source_number:
        sender_id_parts.append(source_number.lstrip("+"))
    if source_name:
        sender_id_parts.append(source_name.replace("/", "_"))

    if not sender_id_parts:
        return None

    sender_pattern = re.sub(r"[^\w\-_\.]", "_", "-".join(sender_id_parts))

    try:
        now = datetime.datetime.now(TIMEZONE)
        candidate_files = [f for f in os.listdir(group_dir) if f.endswith(".md")]

        for filename in candidate_files:
            # Check if the file belongs to the sender
            if sender_pattern not in filename:
                continue

            try:
                # Extract DDHHMM from filename like "DDHHMM-..."
                ts_str = filename.split("-")[0]
                if len(ts_str) != 6:
                    continue

                day = int(ts_str[0:2])
                hour = int(ts_str[2:4])
                minute = int(ts_str[4:6])

                # Validate extracted values
                if not (1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59):
                    continue

                # Reconstruct the file's datetime using current month/year as base
                try:
                    file_dt = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
                except ValueError:
                    # Handle invalid day for this month (e.g., day 31 in February)
                    continue

                # Handle month/year rollovers
                if file_dt > now:
                    # If the file's date is in the future, it must be from the previous month
                    # Calculate previous month safely
                    prev_month = now.month - 1 if now.month > 1 else 12
                    prev_year = now.year if now.month > 1 else now.year - 1

                    try:
                        file_dt = now.replace(
                            year=prev_year, month=prev_month, day=day, hour=hour, minute=minute, second=0, microsecond=0
                        )
                    except ValueError:
                        # Day doesn't exist in previous month either, skip this file
                        continue

                    # If still in the future (shouldn't happen), skip the file
                    if file_dt > now:
                        continue

                # Check if the file is within the append window
                time_diff = now - file_dt
                if time_diff < datetime.timedelta(minutes=APPEND_WINDOW_MINUTES) and (
                    latest_file is None or file_dt > latest_time
                ):
                    latest_time = file_dt
                    latest_file = os.path.join(group_dir, filename)
                    logger.debug(f"Found candidate file: {filename} (age: {time_diff})")

            except (ValueError, IndexError) as e:
                logger.debug(f"Skipping file {filename}: {e}")
                continue

    except FileNotFoundError:
        return None

    if latest_file:
        logger.debug(f"Selected latest file for sender: {latest_file}")
    return latest_file


def _apply_regex_links(text: str | None) -> str | None:
    """
    Wrapper function for backward compatibility.
    Use apply_regex_links from link_formatter module instead.
    """
    return apply_regex_links(text)


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

    if group_title and group_title in IGNORED_GROUPS:
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
    now = datetime.datetime.now(TIMEZONE)

    # --- Append Logic ---
    is_plus_plus_append = PLUS_PLUS_ENABLED and msg and msg.strip().startswith("++")
    is_reply_append = False
    if quote:
        quote_ts = quote.get("id", 0)
        quote_dt = datetime.datetime.fromtimestamp(quote_ts / 1000.0, tz=TIMEZONE)
        if (now - quote_dt) < datetime.timedelta(minutes=APPEND_WINDOW_MINUTES):
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
                content_to_append = []

                # Add TNR and sender info for the appended message
                sender_display = format_sender_display(source_name, source_number)
                content_to_append.append(f"\nTNR: {now.strftime('%d%H%M')} ({now.isoformat()})")
                content_to_append.append(f"Avsändare: {sender_display}")

                if new_text:
                    content_to_append.append("\n" + _apply_regex_links(new_text))

                if attachment_links:
                    content_to_append.append("\n## Bilagor\n")
                    content_to_append.extend(attachment_links)

                with open(latest_file, "a", encoding="utf-8") as f:
                    f.write("\n---\n")
                    f.write("\n".join(content_to_append))
                logger.info(f"APPENDED (reply or ++) TO: {latest_file}")
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
        command = msg.strip()[1:]
        if not command:
            return
        response_filepath = os.path.join("responses", f"{command}.md")
        if os.path.exists(response_filepath):
            try:
                with open(response_filepath, encoding="utf-8") as f:
                    response_text = f.read()
                await _send_reply(group_id, response_text, writer)
                logger.info(f"Sent '{command}' response.")
            except Exception as e:
                logger.error(f"Could not process #{command} command: {e}")
        else:
            logger.info(f"No response file found for command: #{command}")
        return

    # If no message body and no attachments, skip.
    if not msg and not attachments:
        logger.info("Skipping message: No message body and no attachments.")
        return

    if not group_title:
        logger.info("Skipping message: Not a group message.")
        return

    dt = (
        datetime.datetime.fromtimestamp(envelope.get("timestamp") / 1000.0, tz=TIMEZONE)
        if envelope.get("timestamp")
        else now
    )

    path = get_message_filepath(group_title, dt, source_name, source_number)
    group_dir = os.path.dirname(path)
    os.makedirs(group_dir, exist_ok=True)

    file_exists = os.path.exists(path)

    lat, lon = None, None
    if msg:
        maps_url_match = re.search(r"https://maps\.google\.com/maps\?q=([\d.-]+)%2C([\d.-]+)", msg)
        if maps_url_match:
            lat, lon = maps_url_match.groups()

    attachment_links = await _save_attachments(attachments, group_dir, dt, source_name, source_number, reader, writer)

    # --- Prepare content for Markdown file ---
    content_parts = []
    if file_exists:
        content_parts.append("\n---\n")
    else:
        sender_display = format_sender_display(source_name, source_number)

        if lat is not None and lon is not None:
            content_parts.extend(["---", 'locations: ""', "---", ""])

        content_parts.extend(
            [
                f"# {group_title}\n",
                f"TNR: {dt.strftime('%d%H%M')} ({dt.isoformat()})\n",
                f"Avsändare: {sender_display}\n",
                f"Grupp: [[{group_title}]]\n",
                f"Grupp id: {group_id}\n",
            ]
        )
        if lat is not None and lon is not None:
            content_parts.append(f"[Position](geo:{lat},{lon})\n")

    if quote:
        content_parts.extend(_format_quote(quote))

    if msg:
        content_parts.append("\n## Meddelande\n")
        linked_msg = _apply_regex_links(msg.strip())
        content_parts.append(linked_msg)

    if attachment_links:
        content_parts.append("\n## Bilagor\n")
        content_parts.extend(attachment_links)

    content_parts.append("")

    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(content_parts))

    action = "APPENDED TO" if file_exists else "WROTE"
    logger.info(f"{action}: {path}")
