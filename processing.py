import os
import sys
import json
import datetime
import base64
import re
from urllib.parse import urlparse, parse_qs

from formatting import (
    get_message_filepath,
    format_sender_display,
    _format_quote,
    create_message_filename,
)

# ==============================================================================
# MESSAGE PROCESSING
# ==============================================================================

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

    # Extract potential quote from the dataMessage
    dm = envelope.get("dataMessage", {})
    quote = dm.get("quote")
    source_name = envelope.get("sourceName")
    source_number = envelope.get("sourceNumber") or envelope.get("source")

    ts_ms = envelope.get("timestamp")
    dt = (
        datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)
        if ts_ms
        else datetime.datetime.now(datetime.timezone.utc)
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
        content_parts.append(msg.strip())

    if attachment_links:
        content_parts.append("\n## Bilagor\n")
        content_parts.extend(attachment_links)
    
    content_parts.append("") # Ensure a final newline


    # Open in append mode, which creates the file if it doesn't exist.
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(content_parts))

    action = "APPENDED TO" if file_exists else "WROTE"
    print(f"{action}: {path}", file=sys.stderr)
