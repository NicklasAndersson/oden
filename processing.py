import os
import sys
import json
import datetime
import base64
import re
import asyncio
import logging
from typing import Optional, List, Tuple, Dict, Any
from urllib.parse import urlparse, parse_qs

from config import REGEX_PATTERNS, TIMEZONE, APPEND_WINDOW_MINUTES, IGNORED_GROUPS
from formatting import (
    get_message_filepath,
    format_sender_display,
    _format_quote,
    create_message_filename,
    get_safe_group_dir_path,
)

logger = logging.getLogger(__name__)

# ==============================================================================
# MESSAGE PROCESSING
# ==============================================================================

def _find_latest_file_for_sender(group_dir: str, source_name: Optional[str], source_number: Optional[str]) -> Optional[str]:
    """
    Finds the most recent file by a given sender in a group directory.
    Returns the path to the most recent file within APPEND_WINDOW_MINUTES, or None.
    """
    latest_file = None
    latest_time = datetime.datetime.min.replace(tzinfo=TIMEZONE)
    
    # Construct sender identifier for matching filenames
    sender_id_parts = []
    if source_number:
        sender_id_parts.append(source_number.lstrip('+'))
    if source_name:
        sender_id_parts.append(source_name.replace('/', '_'))
    
    if not sender_id_parts:
        return None
    
    sender_pattern = re.sub(r'[^\w\-_\.]', '_', "-".join(sender_id_parts))

    try:
        now = datetime.datetime.now(TIMEZONE)
        candidate_files = [f for f in os.listdir(group_dir) if f.endswith('.md')]

        for filename in candidate_files:
            # Check if the file belongs to the sender
            if sender_pattern not in filename:
                continue

            try:
                # Extract DDHHMM from filename like "DDHHMM-..."
                ts_str = filename.split('-')[0]
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
                    # Subtract one day worth of seconds and recalculate to get previous month
                    file_dt = (file_dt - datetime.timedelta(days=31)).replace(day=day)
                    # If this still fails, skip the file
                    if file_dt > now:
                        continue

                # Check if the file is within the append window
                time_diff = now - file_dt
                if time_diff < datetime.timedelta(minutes=APPEND_WINDOW_MINUTES):
                    if latest_file is None or file_dt > latest_time:
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


def _apply_regex_links(text: Optional[str]) -> Optional[str]:
    """
    Applies regex patterns from configuration to text and converts matches to [[...]] links.
    Avoids linking text that is already inside [[...]].
    """
    if not text or not REGEX_PATTERNS:
        return text
    
    # Find all existing [[...]] patterns to avoid double-linking
    existing_links = set(re.findall(r'\[\[([^\]]+)\]\]', text))
    
    for pattern_name, pattern in REGEX_PATTERNS.items():
        try:
            # Find all matches
            matches = re.finditer(pattern, text)
            for match in matches:
                matched_text = match.group(0)
                # Only link if it's not already in an existing link
                if matched_text not in existing_links:
                    text = text.replace(matched_text, f"[[{matched_text}]]", 1)
                    existing_links.add(matched_text)
        except Exception as e:
            logger.warning(f"Error applying regex pattern '{pattern_name}': {e}")
    
    return text

def _extract_message_details(envelope: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str], List[Dict[str, Any]]]:
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
            dm.get("attachments", [])
        )

    if "syncMessage" in envelope:
        sent = envelope.get("syncMessage", {}).get("sentMessage", {})
        group_info = sent.get("groupInfo", {})
        return (
            sent.get("message"),
            group_info.get("groupName") or group_info.get("title") or group_info.get("name"),
            group_info.get("groupId"),
            sent.get("attachments", [])
        )

    return None, None, None, []


async def _get_attachment_data(attachment_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> Optional[str]:
    """
    Makes a JSON-RPC call to signal-cli to get attachment data by ID.
    Returns base64 encoded data if successful, otherwise None.
    """
    request_id = datetime.datetime.now().microsecond # Simple unique ID for the request
    json_request = {
        "jsonrpc": "2.0",
        "method": "getAttachment",
        "params": {
            "id": attachment_id
        },
        "id": request_id
    }
    request_str = json.dumps(json_request) + "\n"

    try:
        writer.write(request_str.encode('utf-8'))
        await writer.drain()

        # Read response line by line until our request_id is matched
        response_line = await reader.readline() # Assume response is on one line for now
        if not response_line:
            logger.error(f"No response for getAttachment request {request_id}")
            return None
        
        response = json.loads(response_line.decode('utf-8').strip())
        
        if response.get("id") == request_id and "result" in response:
            return response["result"].get("data")
        else:
            logger.error(f"Invalid or unmatched response for getAttachment: {response}")
            return None
    except Exception as e:
        logger.error(f"ERROR calling getAttachment for ID {attachment_id}: {e}")
        return None

async def _save_attachments(attachments: List[Dict[str, Any]], group_dir: str, dt: datetime.datetime, source_name: Optional[str], source_number: Optional[str], reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> List[str]:
    """Saves attachments to a subdirectory and returns a list of markdown links."""
    attachment_links = []
    if not attachments:
        return attachment_links

    # Create a unique subdirectory for attachments for this specific message entry
    attachment_subdir_name = dt.strftime("%Y%m%d%H%M%S") + "_" + create_message_filename(dt, source_name, source_number).replace(".md", "")
    attachment_dir = os.path.join(group_dir, attachment_subdir_name)
    os.makedirs(attachment_dir, exist_ok=True)

    for i, attachment in enumerate(attachments):
        data = attachment.get("data")
        filename = attachment.get("filename") or attachment.get("id")
        attachment_id = attachment.get("id")
        
        if not data and attachment_id:
            logger.info(f"Attempting to fetch attachment data for ID: {attachment_id}")
            retrieved_data = await _get_attachment_data(attachment_id, reader, writer)
            if retrieved_data:
                data = retrieved_data
                logger.info(f"Successfully fetched data for attachment ID: {attachment_id}")
            else:
                logger.warning(f"Failed to fetch data for attachment ID: {attachment_id}")

        if data and filename:
            try:
                decoded_data = base64.b64decode(data)
                safe_filename = f"{i+1}_{filename}"
                attachment_filepath = os.path.join(attachment_dir, safe_filename)
                with open(attachment_filepath, "wb") as f:
                    f.write(decoded_data)
                
                relative_path = os.path.relpath(attachment_filepath, group_dir)
                attachment_links.append(f"![[{attachment_subdir_name}/{safe_filename}]]")
                logger.info(f"Saved attachment: {attachment_filepath}")
            except Exception as e:
                logger.error(f"Could not save attachment {filename}. Error: {e}")
        else:
            missing_parts = [p for p, v in [("data", data), ("filename", filename)] if not v]
            logger.warning(f"Attachment missing {' and '.join(missing_parts)}: {attachment}")
    
    return attachment_links

async def _send_reply(group_id: str, message: str, writer: asyncio.StreamWriter) -> None:
    """Sends a reply message to a given group ID via signal-cli JSON-RPC."""
    request_id = f"send-{datetime.datetime.now().microsecond}"
    json_request = {
        "jsonrpc": "2.0",
        "method": "send",
        "params": {
            "groupId": group_id,
            "message": message
        },
        "id": request_id
    }
    request_str = json.dumps(json_request) + "\n"

    try:
        writer.write(request_str.encode('utf-8'))
        await writer.drain()
        logger.info(f"Sent reply to {group_id}")
    except Exception as e:
        logger.error(f"ERROR sending reply to {group_id}: {e}")



async def process_message(obj: Dict[str, Any], reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
    if msg and msg.strip().startswith('--'):
        logger.info("Skipping message: Starts with '--'.")
        return

    source_name = envelope.get("sourceName")
    source_number = envelope.get("sourceNumber") or envelope.get("source")
    dm = envelope.get("dataMessage", {})
    quote = dm.get("quote")
    now = datetime.datetime.now(TIMEZONE)

    # --- Append Logic ---
    is_plus_plus_append = msg and msg.strip().startswith('++')
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
            append_target_name = None # Name isn't available in the quote object
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
            content_to_append = []
            
            new_text = ""
            if msg:
                new_text = msg.strip().lstrip('++').strip() if is_plus_plus_append else msg.strip()
            
            if new_text:
                content_to_append.append("\n" + _apply_regex_links(new_text))

            if attachments:
                original_group_dir = os.path.dirname(latest_file)
                attachment_links = await _save_attachments(attachments, original_group_dir, now, source_name, source_number, reader, writer)
                if attachment_links:
                    content_to_append.append("\n## Bilagor\n")
                    content_to_append.extend(attachment_links)

            if content_to_append:
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
                    msg = msg.strip().lstrip('++').strip()
        
        # If the append was successful (or a ++ which always consumes the message), we are done.
        # If a reply-append fails, we continue on to process it as a new message.
        if is_plus_plus_append or (is_reply_append and latest_file):
            return

    # --- Handle Standard Commands (#) ---
    if msg and msg.strip().startswith('#'):
        command = msg.strip()[1:]
        if not command:
            return
        response_filepath = os.path.join("responses", f"{command}.md")
        if os.path.exists(response_filepath):
            try:
                with open(response_filepath, "r", encoding="utf-8") as f:
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
            content_parts.extend(["---", "locations: \"\"", "---", ""])

        content_parts.extend([
            f"# {group_title}\n",
            f"TNR: {dt.strftime('%d%H%M')} ({dt.isoformat()})\n",
            f"Avsändare: {sender_display}\n",
            f"Grupp: [[{group_title}]]\n",
            f"Grupp id: {group_id}\n",
        ])
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
