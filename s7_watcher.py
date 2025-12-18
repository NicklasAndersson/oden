#!/usr/bin/env python3
import sys
import json
import os
import datetime
import asyncio
import re

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Directory for Obsidian notes. A subdirectory will be created for each group.
VAULT_PATH = os.path.expanduser("vault")

# signal-cli JSON-RPC endpoint (TCP Socket).
# Ensure signal-cli is running with:
# signal-cli -u YOUR_NUMBER jsonRpc --tcp 127.0.0.1:7583
SIGNAL_RPC_HOST = "127.0.0.1"
SIGNAL_RPC_PORT = 7583


# ==============================================================================
# FILENAME AND CONTENT FORMATTING
# ==============================================================================

def get_safe_group_dir_path(group_title):
    """Sanitizes a group title and returns the full path for the group's directory."""
    safe_title = re.sub(r'[^\w\-_\. ]', '_', group_title)
    return os.path.join(VAULT_PATH, safe_title)


def create_message_filename(dt, source_name, source_number):
    """Creates a sanitized, timestamped filename for a message."""
    ts_str = dt.strftime("%d%H%M")
    
    parts = []
    if source_number:
        parts.append(source_number.replace("+", ""))
    if source_name:
        parts.append(source_name)
    
    if not parts:
        parts.append("unknown")

    safe_source = re.sub(r'[^\w\-_\.]', '_', "-".join(parts))
    return f"{ts_str}-{safe_source}.md"


def format_sender_display(source_name, source_number):
    """Constructs a display string for the sender, including name and number."""
    if source_name and source_number:
        return f"#{source_name} (#{source_number})"
    return source_name or source_number or "Unknown"


def get_message_filepath(group_title, dt, source_name, source_number):
    """Constructs the full, safe path for a new message file."""
    group_dir = get_safe_group_dir_path(group_title)
    filename = create_message_filename(dt, source_name, source_number)
    return os.path.join(group_dir, filename)


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
        )

    if "syncMessage" in envelope:
        sent = envelope.get("syncMessage", {}).get("sentMessage", {})
        group_info = sent.get("groupInfo", {})
        return (
            sent.get("message"),
            group_info.get("groupName") or group_info.get("title") or group_info.get("name"),
            group_info.get("groupId"),
        )

    return None, None, None


def process_message(obj):
    """
    Parses a signal message object and writes it to a markdown file.
    If a file for that sender already exists from the same minute, appends the new message.
    """
    envelope = obj.get("envelope", {})
    if not envelope:
        return

    msg, group_title, group_id = _extract_message_details(envelope)

    if not msg or not group_title:
        print("Skipping message: Not a group message or no message body.", file=sys.stderr)
        return

    source_name = envelope.get("sourceName")
    source_number = envelope.get("sourceNumber") or envelope.get("source")

    ts_ms = envelope.get("timestamp")
    dt = (
        datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)
        if ts_ms
        else datetime.datetime.now(datetime.timezone.utc)
    )

    path = get_message_filepath(group_title, dt, source_name, source_number)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    file_exists = os.path.exists(path)

    if file_exists:
        # File exists, so we just append the new message with a separator.
        content_parts = [
            "\n---\n",  # Markdown horizontal rule for separation
            "## Meddelande\n",
            msg,
            ""
        ]
    else:
        # File doesn't exist, create it with the full header.
        sender_display = format_sender_display(source_name, source_number)
        content_parts = [
            f"# {group_title}\n",
            f"TNR: {dt.strftime('%d%H%M')}",
            f"Avsändare: {sender_display}",
            f"Grupp: #{group_title}",
            f"Grupp id: {group_id}\n",
            "## Meddelande\n",
            msg,
            ""
        ]

    # Open in append mode, which creates the file if it doesn't exist.
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(content_parts))

    action = "APPENDED TO" if file_exists else "WROTE"
    print(f"{action}: {path}", file=sys.stderr)


# ==============================================================================
# DAEMON/LISTENER
# ==============================================================================

async def subscribe_and_listen():
    """Connects to signal-cli via TCP socket, subscribes to messages, and processes them."""
    print(f"Connecting to signal-cli at {SIGNAL_RPC_HOST}:{SIGNAL_RPC_PORT}...", file=sys.stderr)
    
    try:
        reader, writer = await asyncio.open_connection(SIGNAL_RPC_HOST, SIGNAL_RPC_PORT)
    except ConnectionRefusedError as e:
        print(f"\nConnection to signal-cli daemon failed: {e}", file=sys.stderr)
        print("Please ensure signal-cli is running in JSON-RPC mode with a TCP socket, for example:", file=sys.stderr)
        print(f"  signal-cli -u YOUR_SIGNAL_NUMBER jsonrpc --tcp {SIGNAL_RPC_HOST}:{SIGNAL_RPC_PORT}", file=sys.stderr)
        sys.exit(1)

    print("Connection successful. Waiting for messages...", file=sys.stderr)
    
    try:
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
                    process_message(params)
                else:
                    print(f"DEBUG: Received non-message data: {data}", file=sys.stderr)
            except json.JSONDecodeError:
                print(f"ERROR: Received non-JSON message: {message_str}", file=sys.stderr)
            except Exception as e:
                print(f"ERROR: Could not process message.\n  Error: {repr(e)}\n  Message: {message_str}", file=sys.stderr)
    finally:
        writer.close()
        await writer.wait_closed()
        print("\nConnection closed.", file=sys.stderr)


def main():
    """Sets up the vault path and starts the async listener."""
    print("Starting s7_watcher...", file=sys.stderr)
    os.makedirs(VAULT_PATH, exist_ok=True)
    
    try:
        asyncio.run(subscribe_and_listen())
    except KeyboardInterrupt:
        print("\nExiting on user request.", file=sys.stderr)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()