"""
Signal-cli process manager.

Handles starting, stopping, and monitoring the signal-cli daemon process.
Supports bundled JRE and signal-cli for macOS .app distribution.
"""

import asyncio
import contextlib
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from oden.bundle_utils import get_bundle_path, get_bundled_java_path, is_bundled
from oden.config import SIGNAL_CLI_LOG_FILE, SIGNAL_CLI_PATH, SIGNAL_DATA_PATH

logger = logging.getLogger(__name__)


def get_bundled_signal_cli_path() -> str | None:
    """Get path to bundled signal-cli."""
    if not is_bundled():
        return None

    bundle_path = get_bundle_path()
    signal_cli_path = bundle_path / "signal-cli" / "bin" / "signal-cli"

    if signal_cli_path.exists():
        logger.info(f"Found bundled signal-cli at: {signal_cli_path}")
        return str(signal_cli_path)

    logger.warning(f"Bundled signal-cli not found at: {signal_cli_path}")
    return None


def get_signal_cli_env() -> dict:
    """Get environment variables for running signal-cli with bundled JRE."""
    env = os.environ.copy()

    # Set JAVA_HOME if bundled JRE is available
    java_path = get_bundled_java_path()
    if java_path:
        java_home = str(Path(java_path).parent.parent)
        env["JAVA_HOME"] = java_home
        # Prepend Java bin to PATH
        env["PATH"] = str(Path(java_path).parent) + os.pathsep + env.get("PATH", "")
        logger.info(f"Using bundled JAVA_HOME: {java_home}")

    # Set signal-cli data directory to ~/.oden/signal-data
    env["SIGNAL_CLI_CONFIG_DIR"] = str(SIGNAL_DATA_PATH)

    return env


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
        self.env = get_signal_cli_env()

    def _find_executable(self) -> str:
        """Finds the signal-cli executable."""
        # First check for bundled signal-cli (PyInstaller)
        bundled = get_bundled_signal_cli_path()
        if bundled:
            return bundled

        if SIGNAL_CLI_PATH:
            if os.path.exists(SIGNAL_CLI_PATH):
                logger.info(f"Found signal-cli from config: {SIGNAL_CLI_PATH}")
                return SIGNAL_CLI_PATH
            else:
                logger.warning(f"Configured signal_cli_path '{SIGNAL_CLI_PATH}' does not exist.")

        if path := shutil.which("signal-cli"):
            logger.info(f"Found signal-cli in PATH: {path}")
            return path

        # Check for signal-cli in project directory (development)
        bundled_path = "./signal-cli-0.13.23/bin/signal-cli"
        if os.path.exists(bundled_path):
            logger.info(f"Found bundled signal-cli: {bundled_path}")
            return os.path.abspath(bundled_path)

        # Also check older version
        bundled_path_old = "./signal-cli-0.13.22/bin/signal-cli"
        if os.path.exists(bundled_path_old):
            logger.info(f"Found bundled signal-cli: {bundled_path_old}")
            return os.path.abspath(bundled_path_old)

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

        self.process = subprocess.Popen(command, stdout=stdout_target, stderr=stderr_target, env=self.env)

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


def get_existing_accounts() -> list[dict]:
    """Find existing Signal accounts by reading accounts.json directly.

    This is much faster than running signal-cli listAccounts (no JVM startup).

    Returns:
        List of dicts with 'number' key for each account.
    """
    import json as json_module

    accounts = []

    # Check standard signal-cli data locations
    data_paths = []
    if sys.platform == "darwin":
        data_paths.append(Path.home() / ".local" / "share" / "signal-cli")
    elif sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            data_paths.append(Path(local_app_data) / "signal-cli")
    else:
        data_paths.append(Path.home() / ".local" / "share" / "signal-cli")

    # Also check our custom location
    data_paths.append(SIGNAL_DATA_PATH)

    logger.debug(f"Searching for Signal accounts in: {data_paths}")

    for data_path in data_paths:
        accounts_file = data_path / "data" / "accounts.json"
        logger.debug(f"Checking {accounts_file} (exists: {accounts_file.exists()})")
        if accounts_file.exists():
            try:
                with open(accounts_file) as f:
                    data = json_module.load(f)
                    for acc in data.get("accounts", []):
                        number = acc.get("number")
                        if number and not any(a["number"] == number for a in accounts):
                            accounts.append({"number": number})
                logger.info(f"Found {len(accounts)} accounts in {accounts_file}")
            except (json_module.JSONDecodeError, OSError, KeyError) as e:
                logger.warning(f"Error reading {accounts_file}: {e}")

    logger.info(f"Total accounts found: {len(accounts)}")
    return accounts


class SignalLinker:
    """Handles Signal account linking via QR code."""

    def __init__(self, device_name: str = "Oden"):
        self.device_name = device_name
        self.executable = self._find_executable()
        self.env = get_signal_cli_env()
        self.process: subprocess.Popen | None = None
        self.link_uri: str | None = None
        self.linked_number: str | None = None
        self.error: str | None = None
        self.status: str = "idle"  # idle, waiting, linked, error, timeout

    def _find_executable(self) -> str:
        """Finds the signal-cli executable."""
        bundled = get_bundled_signal_cli_path()
        if bundled:
            return bundled

        if SIGNAL_CLI_PATH and os.path.exists(SIGNAL_CLI_PATH):
            return SIGNAL_CLI_PATH

        if path := shutil.which("signal-cli"):
            return path

        # Check for signal-cli in project directory
        for version in ["0.13.23", "0.13.22"]:
            bundled_path = f"./signal-cli-{version}/bin/signal-cli"
            if os.path.exists(bundled_path):
                return os.path.abspath(bundled_path)

        raise FileNotFoundError("signal-cli executable not found.")

    async def start_link(self) -> str | None:
        """Start the linking process and return the device link URI.

        Returns:
            The sgnl:// URI for QR code generation, or None if failed.
        """
        self.status = "waiting"
        self.link_uri = None
        self.linked_number = None
        self.error = None

        command = [
            self.executable,
            "link",
            "-n",
            self.device_name,
        ]

        logger.info(f"Starting signal-cli link: {' '.join(command)}")

        try:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
            )

            # Read the first line which should contain the link URI
            if self.process.stdout:
                line = await asyncio.wait_for(
                    self.process.stdout.readline(),
                    timeout=10.0,
                )
                if line:
                    uri = line.decode("utf-8").strip()
                    if uri.startswith("sgnl://"):
                        self.link_uri = uri
                        logger.info(f"Got link URI: {uri[:50]}...")
                        return uri

            self.status = "error"
            self.error = "Failed to get link URI from signal-cli"
            return None

        except asyncio.TimeoutError:
            self.status = "error"
            self.error = "Timeout waiting for link URI"
            await self.cancel()
            return None
        except Exception as e:
            self.status = "error"
            self.error = str(e)
            logger.error(f"Error starting link: {e}")
            return None

    async def wait_for_link(self, timeout: float = 60.0) -> bool:
        """Wait for the linking to complete.

        Args:
            timeout: Maximum seconds to wait for linking.

        Returns:
            True if successfully linked, False otherwise.
        """
        if not self.process:
            return False

        try:
            # Wait for process to complete (user scans QR code)
            stdout, stderr = await asyncio.wait_for(
                self.process.communicate(),
                timeout=timeout,
            )

            if self.process.returncode == 0:
                # Try to extract the phone number from output
                output = stdout.decode("utf-8") if stdout else ""
                # signal-cli outputs the number on success
                for line in output.split("\n"):
                    line = line.strip()
                    if line.startswith("+"):
                        self.linked_number = line
                        break

                self.status = "linked"
                logger.info(f"Successfully linked to number: {self.linked_number}")
                return True
            else:
                error_output = stderr.decode("utf-8") if stderr else "Unknown error"
                self.status = "error"
                self.error = error_output
                logger.error(f"Link failed: {error_output}")
                return False

        except asyncio.TimeoutError:
            self.status = "timeout"
            self.error = "Timeout waiting for QR code scan"
            logger.warning("Link timeout - user did not scan QR code in time")
            await self.cancel()
            return False
        except Exception as e:
            self.status = "error"
            self.error = str(e)
            logger.error(f"Error during linking: {e}")
            return False

    async def cancel(self) -> None:
        """Cancel the linking process."""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                with contextlib.suppress(ProcessLookupError):
                    self.process.kill()
            self.process = None

    def get_manual_instructions(self) -> str:
        """Get manual linking instructions for terminal."""
        return f"""
## Manuell Signal-länkning

Länkningen tog för lång tid. Följ dessa steg i terminalen:

1. Öppna Terminal

2. Kör följande kommando:
   {self.executable} link -n "{self.device_name}"

3. En QR-kod visas. Scanna den med Signal-appen:
   - Öppna Signal på din telefon
   - Gå till Inställningar → Länkade enheter
   - Tryck på "+" eller "Länka ny enhet"
   - Scanna QR-koden

4. När länkningen är klar, skriv in ditt telefonnummer i fältet ovan
   och klicka "Spara konfiguration".
"""


class SignalRegistrar:
    """Handles Signal account registration with CAPTCHA support."""

    def __init__(self) -> None:
        self.executable = self._find_executable()
        self.env = get_signal_cli_env()
        self.phone_number: str | None = None
        self.use_voice: bool = False
        self.needs_captcha: bool = False
        self.captcha_url: str = "https://signalcaptchas.org/registration/generate.html"
        self.error: str | None = None
        self.status: str = "idle"  # idle, awaiting_captcha, awaiting_code, registered, error

    def _find_executable(self) -> str:
        """Finds the signal-cli executable."""
        bundled = get_bundled_signal_cli_path()
        if bundled:
            return bundled

        if SIGNAL_CLI_PATH and os.path.exists(SIGNAL_CLI_PATH):
            return SIGNAL_CLI_PATH

        if path := shutil.which("signal-cli"):
            return path

        # Check for signal-cli in project directory
        for version in ["0.13.23", "0.13.22"]:
            bundled_path = f"./signal-cli-{version}/bin/signal-cli"
            if os.path.exists(bundled_path):
                return os.path.abspath(bundled_path)

        raise FileNotFoundError("signal-cli executable not found.")

    async def start_register(
        self, phone_number: str, use_voice: bool = False, captcha_token: str | None = None
    ) -> dict:
        """Start the registration process.

        Args:
            phone_number: Phone number in international format (e.g., +46701234567)
            use_voice: If True, request voice call instead of SMS
            captcha_token: Optional CAPTCHA token if required

        Returns:
            dict with keys: success, needs_captcha, error, status
        """
        self.phone_number = phone_number
        self.use_voice = use_voice
        self.error = None

        command = [self.executable, "-u", phone_number, "register"]

        if use_voice:
            command.append("--voice")

        if captcha_token:
            command.extend(["--captcha", captcha_token])

        logger.info(f"Starting registration: {' '.join(command[:4])}...")

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)

            stdout_text = stdout.decode("utf-8") if stdout else ""
            stderr_text = stderr.decode("utf-8") if stderr else ""

            if process.returncode == 0:
                self.status = "awaiting_code"
                self.needs_captcha = False
                logger.info(f"Registration started for {phone_number}, awaiting verification code")
                return {
                    "success": True,
                    "needs_captcha": False,
                    "status": "awaiting_code",
                    "message": f"Verifieringskod skickad till {phone_number} via {'samtal' if use_voice else 'SMS'}",
                }

            # Check if CAPTCHA is required
            combined_output = (stdout_text + stderr_text).lower()
            if "captcha" in combined_output:
                self.status = "awaiting_captcha"
                self.needs_captcha = True
                logger.info("CAPTCHA required for registration")
                return {
                    "success": False,
                    "needs_captcha": True,
                    "status": "awaiting_captcha",
                    "captcha_url": self.captcha_url,
                    "message": "CAPTCHA krävs. Lös CAPTCHA och klistra in länken.",
                }

            # Other error
            self.status = "error"
            self.error = stderr_text or stdout_text or "Registrering misslyckades"
            logger.error(f"Registration failed: {self.error}")
            return {
                "success": False,
                "needs_captcha": False,
                "status": "error",
                "error": self.error,
            }

        except asyncio.TimeoutError:
            self.status = "error"
            self.error = "Timeout vid registrering"
            logger.error("Registration timeout")
            return {"success": False, "status": "error", "error": self.error}
        except Exception as e:
            self.status = "error"
            self.error = str(e)
            logger.error(f"Registration error: {e}")
            return {"success": False, "status": "error", "error": self.error}

    async def verify(self, code: str) -> dict:
        """Verify the registration with the received code.

        Args:
            code: The verification code received via SMS or voice call

        Returns:
            dict with keys: success, error, phone_number
        """
        if not self.phone_number:
            return {"success": False, "error": "Inget telefonnummer registrerat"}

        # Remove any spaces or dashes from code
        code = code.replace(" ", "").replace("-", "")

        command = [self.executable, "-u", self.phone_number, "verify", code]

        logger.info(f"Verifying registration for {self.phone_number}")

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)

            if process.returncode == 0:
                self.status = "registered"
                logger.info(f"Successfully registered {self.phone_number}")
                return {
                    "success": True,
                    "status": "registered",
                    "phone_number": self.phone_number,
                    "message": f"Nummer {self.phone_number} registrerat!",
                }

            stderr_text = stderr.decode("utf-8") if stderr else ""
            self.status = "error"
            self.error = stderr_text or "Verifiering misslyckades"
            logger.error(f"Verification failed: {self.error}")
            return {"success": False, "status": "error", "error": self.error}

        except asyncio.TimeoutError:
            self.status = "error"
            self.error = "Timeout vid verifiering"
            return {"success": False, "status": "error", "error": self.error}
        except Exception as e:
            self.status = "error"
            self.error = str(e)
            logger.error(f"Verification error: {e}")
            return {"success": False, "status": "error", "error": self.error}
