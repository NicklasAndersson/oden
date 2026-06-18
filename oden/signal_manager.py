"""
Signal-cli process manager.

Handles starting, stopping, and monitoring the signal-cli daemon process.
Supports bundled JRE and signal-cli for macOS .app distribution.
"""

import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from oden import config as cfg
from oden.bundle_utils import get_bundle_path, get_bundled_java_path, is_bundled

logger = logging.getLogger(__name__)

_SIGNAL_CLI_MAIN_CLASS = "org.asamk.signal.Main"


def get_bundled_signal_cli_path() -> str | None:
    """Get path to bundled signal-cli."""
    if not is_bundled():
        return None

    bundle_path = get_bundle_path()
    signal_cli_bin_dir = bundle_path / "signal-cli" / "bin"

    # Windows requires the .bat launcher (executing the Unix shell script
    # raises WinError 193: not a valid Win32 application).
    if sys.platform == "win32":
        candidates = [
            signal_cli_bin_dir / "signal-cli.bat",
            signal_cli_bin_dir / "signal-cli.exe",
            signal_cli_bin_dir / "signal-cli",
        ]
    else:
        candidates = [
            signal_cli_bin_dir / "signal-cli",
        ]

    for signal_cli_path in candidates:
        if signal_cli_path.exists():
            logger.info(f"Found bundled signal-cli at: {signal_cli_path}")
            return str(signal_cli_path)

    logger.warning(f"Bundled signal-cli not found in: {signal_cli_bin_dir}")
    return None


def _get_standard_signal_cli_paths() -> list[Path]:
    """Return standard signal-cli data directory paths for the current platform."""
    paths: list[Path] = []

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            paths.append(Path(local_app_data) / "signal-cli")

    # signal-cli commonly uses ~/.local/share/signal-cli on macOS/Linux,
    # and some Windows installs do the same through Java path defaults.
    paths.append(Path.home() / ".local" / "share" / "signal-cli")

    deduped_paths: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            seen.add(path)
            deduped_paths.append(path)
    return deduped_paths


def get_signal_data_search_paths() -> list[Path]:
    """Return all signal-cli data directories Oden should inspect."""
    data_paths = _get_standard_signal_cli_paths()
    if cfg.SIGNAL_DATA_PATH not in data_paths:
        data_paths.append(cfg.SIGNAL_DATA_PATH)
    return data_paths


def resolve_signal_data_path() -> Path:
    """Determine the best signal-cli data directory to use.

    Prefers the Oden-specific path (SIGNAL_DATA_PATH) if it contains account
    data.  Otherwise checks the standard signal-cli data locations.  Falls
    back to SIGNAL_DATA_PATH so new accounts get created there.
    """
    oden_accounts = cfg.SIGNAL_DATA_PATH / "data" / "accounts.json"
    if oden_accounts.exists():
        return cfg.SIGNAL_DATA_PATH

    for std_path in _get_standard_signal_cli_paths():
        if (std_path / "data" / "accounts.json").exists():
            logger.info(
                "Oden signal-data dir (%s) has no accounts; using standard signal-cli location: %s",
                cfg.SIGNAL_DATA_PATH,
                std_path,
            )
            return std_path

    # No accounts anywhere – use the Oden path so new accounts land there
    return cfg.SIGNAL_DATA_PATH


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

    # Resolve signal-cli data directory (may fall back to standard location)
    env["SIGNAL_CLI_CONFIG_DIR"] = str(resolve_signal_data_path())

    return env


def get_process_creationflags() -> int:
    """Return platform-appropriate subprocess creation flags."""
    if sys.platform != "win32":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _get_signal_cli_install_dir(executable: str) -> Path | None:
    """Return the signal-cli installation root when executable lives in bin/."""
    executable_path = Path(executable)
    if executable_path.parent.name.lower() != "bin":
        return None

    install_dir = executable_path.parent.parent
    if (install_dir / "lib").exists():
        return install_dir
    return None


def build_signal_cli_command(executable: str, args: list[str]) -> list[str]:
    """Build a command line for invoking signal-cli on the current platform."""
    install_dir = _get_signal_cli_install_dir(executable)

    if sys.platform == "win32" and install_dir is not None:
        java_path = get_bundled_java_path()
        if java_path:
            classpath = str(install_dir / "lib" / "*")
            return [
                java_path,
                "-cp",
                classpath,
                _SIGNAL_CLI_MAIN_CLASS,
                *args,
            ]

        windows_launcher = install_dir / "bin" / "signal-cli.bat"
        if windows_launcher.exists():
            return ["cmd.exe", "/c", str(windows_launcher), *args]

    command = [executable, *args]
    if sys.platform == "win32" and executable.lower().endswith((".bat", ".cmd")):
        return ["cmd.exe", "/c", *command]
    return command


def is_signal_cli_running(host: str, port: int) -> bool:
    """Checks if the signal-cli RPC server is reachable."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.settimeout(1)
            s.connect((host, port))
            return True
        except (OSError, ConnectionRefusedError):
            return False


def find_signal_cli_executable() -> str:
    """Finds the signal-cli executable.

    Checks (in order): bundled PyInstaller path, config path,
    system PATH, project directory.

    Raises:
        FileNotFoundError: If no signal-cli executable can be found.
    """
    bundled = get_bundled_signal_cli_path()
    if bundled:
        return bundled

    if cfg.SIGNAL_CLI_PATH:
        if os.path.exists(cfg.SIGNAL_CLI_PATH):
            logger.info(f"Found signal-cli from config: {cfg.SIGNAL_CLI_PATH}")
            return cfg.SIGNAL_CLI_PATH
        else:
            logger.warning(f"Configured signal_cli_path '{cfg.SIGNAL_CLI_PATH}' does not exist.")

    if path := shutil.which("signal-cli"):
        logger.info(f"Found signal-cli in PATH: {path}")
        return path

    # Check for signal-cli in project directory (development)
    for version in ["0.14.5", "0.14.4.1", "0.14.1", "0.13.23"]:
        if sys.platform == "win32":
            dev_candidates = [
                f"./signal-cli-{version}/bin/signal-cli.bat",
                f"./signal-cli-{version}/bin/signal-cli.exe",
                f"./signal-cli-{version}/bin/signal-cli",
            ]
        else:
            dev_candidates = [f"./signal-cli-{version}/bin/signal-cli"]

        for bundled_path in dev_candidates:
            if os.path.exists(bundled_path):
                logger.info(f"Found bundled signal-cli: {bundled_path}")
                return os.path.abspath(bundled_path)

    raise FileNotFoundError(
        "signal-cli executable not found. Please install it, place it in the project directory, or configure 'signal_cli_path' in the web GUI."
    )


class SignalManager:
    """Manages the signal-cli subprocess."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.process = None
        self.executable = find_signal_cli_executable()
        self.log_file_handle = None
        self.env = get_signal_cli_env()

    def start(self) -> None:
        """Starts the signal-cli daemon."""
        if is_signal_cli_running(self.host, self.port):
            logger.info("signal-cli is already running.")
            return

        command = build_signal_cli_command(
            self.executable,
            [
                "daemon",
                "--tcp",
                f"{self.host}:{self.port}",
                "--receive-mode",
                "on-connection",
            ],
        )

        logger.info(f"Starting signal-cli: {' '.join(command)}")

        if cfg.SIGNAL_CLI_LOG_FILE:
            try:
                self.log_file_handle = open(cfg.SIGNAL_CLI_LOG_FILE, "a")  # noqa: SIM115
                stdout_target = self.log_file_handle
                stderr_target = self.log_file_handle
                logger.info(f"Redirecting signal-cli output to {cfg.SIGNAL_CLI_LOG_FILE}")
            except OSError as e:
                logger.warning(f"Could not open log file {cfg.SIGNAL_CLI_LOG_FILE}: {e}. Logging to stderr.")
                stdout_target = subprocess.PIPE
                stderr_target = subprocess.PIPE
        else:
            stdout_target = subprocess.PIPE
            stderr_target = subprocess.PIPE

        self.process = subprocess.Popen(
            command,
            stdout=stdout_target,
            stderr=stderr_target,
            env=self.env,
            creationflags=get_process_creationflags(),
        )

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

    # Build search list: standard locations + Oden custom location
    data_paths = get_signal_data_search_paths()

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
