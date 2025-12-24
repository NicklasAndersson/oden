import os
import sys
import json
import datetime
import base64
import re
from urllib.parse import urlparse, parse_qs

from config import REGEX_PATTERNS, TIMEZONE
from formatting import (
    get_message_filepath,
    format_sender_display,
    _format_quote,
    create_message_filename,
    get_safe_group_dir_path,
)

# ==============================================================================
# MESSAGE PROCESSING
# ==============================================================================

def _find_latest_file_for_sender(group_dir, source_name, source_number):
    """
    Finds the most recent file by a given sender in a group directory,
    if it's not older than 30 minutes.
    """
    latest_file = None
    latest_time = datetime.datetime.min.replace(tzinfo=TIMEZONE)
    
    # Construct a pattern to identify files from this sender
    # This is fragile, but mirrors the logic in create_message_filename
    sender_id_parts = []
    if source_number:
        sender_id_parts.append(source_number.lstrip('+'))
    if source_name:
        sender_id_parts.append(source_name.replace('/', '_')) # Basic sanitization
    
    sender_pattern = "*" + re.sub(r'[^\w\-_\.]', '_', "-".join(sender_id_parts)) + ".md"

    try:
        now = datetime.datetime.now(TIMEZONE)
        candidate_files = [f for f in os.listdir(group_dir) if f.endswith('.md')]

        for filename in candidate_files:
            # Check if the file belongs to the sender
            if not re.search(sender_pattern.replace('*',''), filename, re.IGNORECASE):
                 continue

            try:
                # Extract DDHHMM from filename like "DDHHMM-..."
                ts_str = filename.split('-')[0]
                day = int(ts_str[0:2])
                hour = int(ts_str[2:4])
                minute = int(ts_str[4:6])

                # Reconstruct the file's datetime
                file_dt = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
                
                # Handle month/year rollovers
                if file_dt > now:
                    # If the file's date is in the future, it must be from the previous month
                    file_dt -= datetime.timedelta(days=now.day) # Go to start of month approx.
                    # This is imperfect but should work for a 30-min window

                if (now - file_dt) < datetime.timedelta(minutes=30):
                    if latest_file is None or file_dt > latest_time:
                        latest_time = file_dt
                        latest_file = os.path.join(group_dir, filename)

            except (ValueError, IndexError):
                continue # Ignore files with non-matching name format
    
    except FileNotFoundError:
        return None # Group directory doesn't exist

    return latest_file


def _apply_regex_links(text):
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
            print(f"WARNING: Error applying regex pattern '{pattern_name}': {e}", file=sys.stderr)
    
    return text

def _extract_message_details(envelope):
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


async def _get_attachment_data(attachment_id, reader, writer):
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
            print(f"ERROR: No response for getAttachment request {request_id}", file=sys.stderr)
            return None
        
        response = json.loads(response_line.decode('utf-8').strip())
        
        if response.get("id") == request_id and "result" in response:
            return response["result"].get("data")
        else:
            print(f"ERROR: Invalid or unmatched response for getAttachment: {response}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"ERROR calling getAttachment for ID {attachment_id}: {e}", file=sys.stderr)
        return None


async def _send_reply(group_id, message, writer):
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
        print(f"Sent reply to {group_id}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR sending reply to {group_id}: {e}", file=sys.stderr)



async def process_message(obj, reader, writer):
    """
    Parses a signal message object and writes it to a markdown file, including attachments.
    If a file for that sender already exists from the same minute, appends the new message.
    """
    envelope = obj.get("envelope", {})
    if not envelope:
        return

    msg, group_title, group_id, attachments = _extract_message_details(envelope)
    source_name = envelope.get("sourceName")
    source_number = envelope.get("sourceNumber") or envelope.get("source")
    dm = envelope.get("dataMessage", {})
    quote = dm.get("quote")
    now = datetime.datetime.now(TIMEZONE)

    # --- Append Logic ---
    # Determine if this message is an append command, either by '++' or by replying to self.
    is_plus_plus_append = msg and msg.strip().startswith('++')
    is_reply_append = False
    if quote and quote.get("author") == source_number:
        quote_ts = quote.get("id", 0)
        quote_dt = datetime.datetime.fromtimestamp(quote_ts / 1000.0, tz=TIMEZONE)
        if (now - quote_dt) < datetime.timedelta(minutes=30):
            is_reply_append = True

    if is_plus_plus_append or is_reply_append:
        if not group_title or not (source_name or source_number):
            print("ERROR: Cannot append message, missing group or source.", file=sys.stderr)
            return

        group_dir = get_safe_group_dir_path(group_title)
        latest_file = _find_latest_file_for_sender(group_dir, source_name, source_number)

        if latest_file:
            content_to_append = []
            # Strip '++' prefix if it exists
            new_text = msg.strip().lstrip('++').strip() if is_plus_plus_append else msg.strip()
            
            if new_text:
                content_to_append.append("\n" + _apply_regex_links(new_text))

            if attachments:
                # This is complex. For now, let's just add a note about the attachment.
                # A full implementation would reuse the attachment handling logic.
                content_to_append.append("\n**Tillägg med bilagor:**")
                for att in attachments:
                    content_to_append.append(f"- {att.get('filename', 'Okänd fil')}")

            if content_to_append:
                with open(latest_file, "a", encoding="utf-8") as f:
                    f.write("\n---\n")
                    f.write("\n".join(content_to_append))
                print(f"APPENDED (reply or ++) TO: {latest_file}", file=sys.stderr)
            else:
                print(f"INFO: Ignoring empty append message.", file=sys.stderr)

        else:
            print(f"APPEND FAILED: No recent file (<30min) found for sender.", file=sys.stderr)
            # As a fallback, process it as a new message but without the append command/quote
            if is_reply_append:
                quote = None # Unset quote to prevent it being formatted in the new file
        
        if is_plus_plus_append:
            return # Always stop processing for '++' messages
        elif is_reply_append and latest_file:
            return # Stop processing if we successfully appended to a file on reply
        # If reply-append fails, let it fall through to be processed as a new message.

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
                print(f"Sent '{command}' response.", file=sys.stderr)
            except Exception as e:
                print(f"ERROR: Could not process #{command} command: {e}", file=sys.stderr)
        else:
            print(f"No response file found for command: #{command}", file=sys.stderr)

        return

    # If no message body and no attachments, skip.
    if not msg and not attachments:
        print("Skipping message: No message body and no attachments.", file=sys.stderr)
        return
    
    if not group_title:
        print("Skipping message: Not a group message.", file=sys.stderr)
        return

    # ts_ms is already fetched, re-use 'now' from above
    dt = (
        datetime.datetime.fromtimestamp(envelope.get("timestamp") / 1000.0, tz=TIMEZONE)
        if envelope.get("timestamp")
        else now
    )

    path = get_message_filepath(group_title, dt, source_name, source_number)
    group_dir = os.path.dirname(path)
    os.makedirs(group_dir, exist_ok=True)


    file_exists = os.path.exists(path)

    # Check for Google Maps link and extract coordinates early
    lat, lon = None, None
    if msg:
        maps_url_match = re.search(r"https://maps\.google\.com/maps\?q=([\d.-]+)%2C([\d.-]+)", msg)
        if maps_url_match:
            lat, lon = maps_url_match.groups()

    # --- Handle Attachments ---
    attachment_links = []
    if attachments:
        # Create a unique subdirectory for attachments for this specific message entry
        # Using the message timestamp (up to second) for the attachment folder name
        attachment_subdir_name = dt.strftime("%Y%m%d%H%M%S") + "_" + create_message_filename(dt, source_name, source_number).replace(".md", "")
        attachment_dir = os.path.join(group_dir, attachment_subdir_name)
        os.makedirs(attachment_dir, exist_ok=True)

        for i, attachment in enumerate(attachments):
            data = attachment.get("data")
            # Use 'filename' if available, otherwise fallback to 'id'
            filename = attachment.get("filename") or attachment.get("id")
            attachment_id = attachment.get("id") # Get the attachment ID for potential retrieval
            
            if not data and attachment_id: # If data is missing but we have an ID, try to fetch it
                print(f"Attempting to fetch attachment data for ID: {attachment_id}", file=sys.stderr)
                retrieved_data = await _get_attachment_data(attachment_id, reader, writer)
                if retrieved_data:
                    data = retrieved_data
                    print(f"Successfully fetched data for attachment ID: {attachment_id}", file=sys.stderr)
                else:
                    print(f"Failed to fetch data for attachment ID: {attachment_id}", file=sys.stderr)

            if data and filename:
                try:
                    decoded_data = base64.b64decode(data)
                    # Create a safe filename for the attachment to avoid issues with special characters
                    safe_filename = f"{i+1}_{filename}" # Prefix with index to ensure uniqueness
                    attachment_filepath = os.path.join(attachment_dir, safe_filename)

                    with open(attachment_filepath, "wb") as f:
                        f.write(decoded_data)
                    
                    # Generate Markdown link for the attachment
                    # Obsidian relative path link for attachments
                    relative_path = os.path.relpath(attachment_filepath, group_dir)
                    attachment_links.append(f"![[{attachment_subdir_name}/{safe_filename}]]")
                    print(f"Saved attachment: {attachment_filepath}", file=sys.stderr)
                except Exception as e:
                    print(f"ERROR: Could not save attachment {filename}. Error: {e}", file=sys.stderr)
            else:
                missing_parts = []
                if not data:
                    missing_parts.append("data")
                if not filename:
                    missing_parts.append("filename")
                print(f"WARNING: Attachment missing {' and '.join(missing_parts)}: {attachment}", file=sys.stderr)


    # --- Prepare content for Markdown file ---
    content_parts = []
    if file_exists:
        # File exists, so we just append the new message with a separator.
        content_parts.append("\n---\n")  # Markdown horizontal rule for separation
    else:
        # File doesn't exist, create it with the full header.
        sender_display = format_sender_display(source_name, source_number)
        
        # Add properties block if coordinates are found
        if lat is not None and lon is not None:
            content_parts.extend([
                "---",
                "locations: \"\"",
                "---",
                "" # Ensure a newline after the properties block
            ])

        content_parts.extend([
            f"# {group_title}\n",
            f"TNR: {dt.strftime('%d%H%M')}\n",
            f"Avsändare: {sender_display}\n",
            f"Grupp: [[{group_title}]]\n",
            f"Grupp id: {group_id}\n",
        ])
        if lat is not None and lon is not None:
            content_parts.append(f"[Position](geo:{lat},{lon})\n")


    if quote:
        content_parts.extend(_format_quote(quote))

    if msg: # Only add message header if there's actual text message
        content_parts.append("\n## Meddelande\n")
        # Apply regex linking to the message
        linked_msg = _apply_regex_links(msg.strip())
        content_parts.append(linked_msg)

    if attachment_links:
        content_parts.append("\n## Bilagor\n")
        content_parts.extend(attachment_links)
    
    content_parts.append("") # Ensure a final newline


    # Open in append mode, which creates the file if it doesn't exist.
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(content_parts))

    action = "APPENDED TO" if file_exists else "WROTE"
    print(f"{action}: {path}", file=sys.stderr)
