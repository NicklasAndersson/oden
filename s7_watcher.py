#!/usr/bin/env python3
import sys
import json
import os
import asyncio
import subprocess
import time
import socket

from config import VAULT_PATH, INBOX_PATH, SIGNAL_NUMBER
from processing import process_message

# Configuration for signal-cli RPC
SIGNAL_RPC_HOST = os.environ.get("SIGNAL_RPC_HOST", "127.0.0.1")
SIGNAL_RPC_PORT = int(os.environ.get("SIGNAL_RPC_PORT", "7583"))

def is_signal_cli_running(host, port):
    """
    Checks if signal-cli RPC server is reachable.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.settimeout(1)
            s.connect((host, port))
            return True
        except (socket.error, ConnectionRefusedError):
            return False

# ==============================================================================
# DAEMON/LISTENER
# ==============================================================================

async def subscribe_and_listen():
    """Connects to signal-cli via TCP socket, subscribes to messages, and processes them."""
    print(f"Connecting to signal-cli at {SIGNAL_RPC_HOST}:{SIGNAL_RPC_PORT}...", file=sys.stderr)
    
    reader = None
    writer = None
    try:
        reader, writer = await asyncio.open_connection(SIGNAL_RPC_HOST, SIGNAL_RPC_PORT, limit=1024 * 1024 * 100) # 100 MB limit
        print("Connection successful. Waiting for messages...", file=sys.stderr)
        
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
                    print(f"DEBUG: Received non-message data: {data}", file=sys.stderr)
            except json.JSONDecodeError:
                print(f"ERROR: Received non-JSON message: {message_str}", file=sys.stderr)
            except Exception as e:
                print(f"ERROR: Could not process message.\n  Error: {repr(e)}\n  Message: {message_str}", file=sys.stderr)

    except ConnectionRefusedError as e:
        print(f"\nConnection to signal-cli daemon failed: {e}", file=sys.stderr)
        print("Please ensure signal-cli is running in JSON-RPC mode with a TCP socket, for example:", file=sys.stderr)
        print(f"  signal-cli -u YOUR_SIGNAL_NUMBER jsonrpc --tcp {SIGNAL_RPC_HOST}:{SIGNAL_RPC_PORT}", file=sys.stderr)
        sys.exit(1)
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        print("\nConnection closed.", file=sys.stderr)

def main():
    """Sets up the vault path, ensures signal-cli is running, and starts the async listener."""
    print("Starting s7_watcher...", file=sys.stderr)
    os.makedirs(INBOX_PATH, exist_ok=True) # Ensure inbox directory exists

    if SIGNAL_NUMBER == "YOUR_SIGNAL_NUMBER":
        print("\nERROR: Please update 'Number' in config.ini with your Signal number.", file=sys.stderr)
        sys.exit(1)

    if not is_signal_cli_running(SIGNAL_RPC_HOST, SIGNAL_RPC_PORT):
            print("Failed to ensure signal-cli is running. Exiting.", file=sys.stderr)
            sys.exit(1)
    else:
        print("signal-cli daemon is already running.", file=sys.stderr)
    
    try:
        asyncio.run(subscribe_and_listen())
    except KeyboardInterrupt:
        print("\nExiting on user request.", file=sys.stderr)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
