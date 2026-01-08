"""
Signal-cli process manager.

Handles starting, stopping, and monitoring the signal-cli daemon process.
"""

import logging
import os
import shutil
import socket
import subprocess
import time

from oden.config import SIGNAL_CLI_LOG_FILE, SIGNAL_CLI_PATH

logger = logging.getLogger(__name__)


def is_signal_cli_running(host: str, port: int) -> bool:
    """Checks if the signal-cli RPC server is reachable."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.settimeout(1)
            s.connect((host, port))
            return True
        except (OSError, ConnectionRefusedError):
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
                logger.info(f"Found signal-cli from config: {SIGNAL_CLI_PATH}")
                return SIGNAL_CLI_PATH
            else:
                logger.warning(f"Configured signal_cli_path '{SIGNAL_CLI_PATH}' does not exist.")

        if path := shutil.which("signal-cli"):
            logger.info(f"Found signal-cli in PATH: {path}")
            return path

        bundled_path = "./signal-cli-0.13.22/bin/signal-cli"
        if os.path.exists(bundled_path):
            logger.info(f"Found bundled signal-cli: {bundled_path}")
            return os.path.abspath(bundled_path)

        raise FileNotFoundError(
            "signal-cli executable not found. Please install it, place it in the project directory, or configure 'signal_cli_path' in config.ini."
        )

    def start(self) -> None:
        """Starts the signal-cli daemon."""
        if is_signal_cli_running(self.host, self.port):
            logger.info("signal-cli is already running.")
            return

        command = [
            self.executable,
            "-u",
            self.number,
            "daemon",
            "--tcp",
            f"{self.host}:{self.port}",
            "--receive-mode",
            "on-connection",
        ]

        logger.info(f"Starting signal-cli: {' '.join(command)}")

        if SIGNAL_CLI_LOG_FILE:
            try:
                self.log_file_handle = open(SIGNAL_CLI_LOG_FILE, "a")  # noqa: SIM115
                stdout_target = self.log_file_handle
                stderr_target = self.log_file_handle
                logger.info(f"Redirecting signal-cli output to {SIGNAL_CLI_LOG_FILE}")
            except OSError as e:
                logger.warning(f"Could not open log file {SIGNAL_CLI_LOG_FILE}: {e}. Logging to stderr.")
                stdout_target = subprocess.PIPE
                stderr_target = subprocess.PIPE
        else:
            stdout_target = subprocess.PIPE
            stderr_target = subprocess.PIPE

        self.process = subprocess.Popen(command, stdout=stdout_target, stderr=stderr_target)

        # Poll for up to 15 seconds for the daemon to start
        for _ in range(15):
            if is_signal_cli_running(self.host, self.port):
                logger.info("signal-cli started successfully.")
                return
            time.sleep(1)

        # If it's still not running, get output and raise error
        self.process.kill()
        # Only try to communicate if pipes were used
        if stdout_target == subprocess.PIPE:
            stdout, stderr = self.process.communicate()
            logger.error("Failed to start signal-cli daemon within 15 seconds.")
            if stdout:
                logger.error(f"Stdout: {stdout.decode()}")
            if stderr:
                logger.error(f"Stderr: {stderr.decode()}")
        else:
            logger.error("Failed to start signal-cli daemon within 15 seconds. Check log file for details.")

        raise RuntimeError("Could not start signal-cli.")

    def stop(self) -> None:
        """Stops the signal-cli daemon."""
        if self.process:
            logger.info("Stopping signal-cli...")
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("signal-cli did not terminate gracefully, killing.")
                self.process.kill()
            self.process = None
            logger.info("signal-cli stopped.")
        if self.log_file_handle:
            self.log_file_handle.close()
            self.log_file_handle = None
