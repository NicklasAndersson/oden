import sys
import json
import os
import asyncio
import subprocess
import time
import socket
import shutil
from typing import Optional

from config import (
    VAULT_PATH, 
    SIGNAL_NUMBER, 
    DISPLAY_NAME,
    SIGNAL_CLI_PATH, 
    UNMANAGED_SIGNAL_CLI, 
    SIGNAL_CLI_HOST, 
    SIGNAL_CLI_PORT,
    SIGNAL_CLI_LOG_FILE
)
from processing import process_message

def is_signal_cli_running(host: str, port: int) -> bool:
    """Checks if the signal-cli RPC server is reachable."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.settimeout(1)
            s.connect((host, port))
            return True
        except (socket.error, ConnectionRefusedError):
            return False

class SignalManager:
    """Manages the signal-cli subprocess."""

    def __init__(self, number: str, host: str, port: int) -> None:
        self.number = number
        self.host = host
        self.port = port
        self.process = None
        self.executable = self._find_executable()
        self.log_file_handle = None

    def _find_executable(self) -> str:
        """Finds the signal-cli executable."""
        if SIGNAL_CLI_PATH:
            if os.path.exists(SIGNAL_CLI_PATH):
                print(f"Found signal-cli from config: {SIGNAL_CLI_PATH}", file=sys.stderr)
                return SIGNAL_CLI_PATH
            else:
                print(f"Warning: Configured signal_cli_path '{SIGNAL_CLI_PATH}' does not exist.", file=sys.stderr)

        if (path := shutil.which("signal-cli")):
            print(f"Found signal-cli in PATH: {path}", file=sys.stderr)
            return path
        
        bundled_path = "./signal-cli-0.13.22/bin/signal-cli"
        if os.path.exists(bundled_path):
            print(f"Found bundled signal-cli: {bundled_path}", file=sys.stderr)
            return os.path.abspath(bundled_path)

        raise FileNotFoundError("signal-cli executable not found. Please install it, place it in the project directory, or configure 'signal_cli_path' in config.ini.")

    def start(self) -> None:
        """Starts the signal-cli daemon."""
        if is_signal_cli_running(self.host, self.port):
            print("signal-cli is already running.", file=sys.stderr)
            return

        command = [
            self.executable,
            "-u", self.number,
            "daemon",
            "--tcp", f"{self.host}:{self.port}",
            "--receive-mode", "on-connection"
        ]
        
        print(f"Starting signal-cli: {' '.join(command)}", file=sys.stderr)

        if SIGNAL_CLI_LOG_FILE:
            try:
                self.log_file_handle = open(SIGNAL_CLI_LOG_FILE, 'a')
                stdout_target = self.log_file_handle
                stderr_target = self.log_file_handle
                print(f"Redirecting signal-cli output to {SIGNAL_CLI_LOG_FILE}", file=sys.stderr)
            except IOError as e:
                print(f"WARNING: Could not open log file {SIGNAL_CLI_LOG_FILE}: {e}. Logging to stderr.", file=sys.stderr)
                stdout_target = subprocess.PIPE
                stderr_target = subprocess.PIPE
        else:
            stdout_target = subprocess.PIPE
            stderr_target = subprocess.PIPE


        self.process = subprocess.Popen(command, stdout=stdout_target, stderr=stderr_target)
        
        # Poll for up to 15 seconds for the daemon to start
        for i in range(15):
            if is_signal_cli_running(self.host, self.port):
                print("signal-cli started successfully.", file=sys.stderr)
                return
            time.sleep(1)

        # If it's still not running, get output and raise error
        self.process.kill()
        # Only try to communicate if pipes were used
        if stdout_target == subprocess.PIPE:
            stdout, stderr = self.process.communicate()
            print("Failed to start signal-cli daemon within 15 seconds.", file=sys.stderr)
            if stdout:
                print(f"Stdout: {stdout.decode()}", file=sys.stderr)
            if stderr:
                print(f"Stderr: {stderr.decode()}", file=sys.stderr)
        else:
            print("Failed to start signal-cli daemon within 15 seconds. Check log file for details.", file=sys.stderr)

        raise RuntimeError("Could not start signal-cli.")


    def stop(self) -> None:
        """Stops the signal-cli daemon."""
        if self.process:
            print("Stopping signal-cli...", file=sys.stderr)
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("signal-cli did not terminate gracefully, killing.", file=sys.stderr)
                self.process.kill()
            self.process = None
            print("signal-cli stopped.", file=sys.stderr)
        if self.log_file_handle:
            self.log_file_handle.close()
            self.log_file_handle = None

# ==============================================================================
# DAEMON/LISTENER
# ==============================================================================

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
        print(f"Attempting to update profile name to '{display_name}'...", file=sys.stderr)
        writer.write(request_str.encode('utf-8'))
        await writer.drain()
        # Note: We are not waiting for a response here to avoid blocking.
        # The update is "fire and forget".
        print("Profile name update request sent.", file=sys.stderr)
    except Exception as e:
        print(f"ERROR sending updateProfile request: {e}", file=sys.stderr)

async def subscribe_and_listen(host: str, port: int) -> None:
    """Connects to signal-cli via TCP socket, subscribes to messages, and processes them."""
    print(f"Connecting to signal-cli at {host}:{port}...", file=sys.stderr)
    
    reader = None
    writer = None
    try:
        reader, writer = await asyncio.open_connection(host, port, limit=1024 * 1024 * 100) # 100 MB limit
        print("Connection successful. Waiting for messages...", file=sys.stderr)

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
                         print(f"DEBUG: Received non-message data: {data}", file=sys.stderr)
            except json.JSONDecodeError:
                print(f"ERROR: Received non-JSON message: {message_str}", file=sys.stderr)
            except Exception as e:
                print(f"ERROR: Could not process message.\n  Error: {repr(e)}\n  Message: {message_str}", file=sys.stderr)

    except ConnectionRefusedError as e:
        print(f"\nConnection to signal-cli daemon failed: {e}", file=sys.stderr)
        print("Please ensure signal-cli is running in JSON-RPC mode with a TCP socket.", file=sys.stderr)
        sys.exit(1)
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        print("\nConnection closed.", file=sys.stderr)

def main() -> None:
    """Sets up the vault path, starts signal-cli, and begins listening."""
    print("Starting s7_watcher...", file=sys.stderr)

    if SIGNAL_NUMBER == "YOUR_SIGNAL_NUMBER":
        print("ERROR: Please set your signal number in config.ini", file=sys.stderr)
        sys.exit(1)

    if UNMANAGED_SIGNAL_CLI:
        if not is_signal_cli_running(SIGNAL_CLI_HOST, SIGNAL_CLI_PORT):
            print("signal-cli is not running. Please start it manually.", file=sys.stderr)
            sys.exit(1)
        print("Running in unmanaged mode. Assuming signal-cli is already running.", file=sys.stderr)
        try:
            asyncio.run(subscribe_and_listen(SIGNAL_CLI_HOST, SIGNAL_CLI_PORT))
        except (KeyboardInterrupt, SystemExit):
            print("\nExiting on user request.", file=sys.stderr)
        except Exception as e:
            print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(0)
    else:
        signal_manager = SignalManager(SIGNAL_NUMBER, SIGNAL_CLI_HOST, SIGNAL_CLI_PORT)
        try:
            signal_manager.start()
            asyncio.run(subscribe_and_listen(SIGNAL_CLI_HOST, SIGNAL_CLI_PORT))
        except (KeyboardInterrupt, SystemExit):
            print("\nExiting on user request.", file=sys.stderr)
        except Exception as e:
            print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        finally:
            signal_manager.stop()
            print("s7_watcher shut down.", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
