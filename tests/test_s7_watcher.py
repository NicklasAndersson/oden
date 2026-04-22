import socket
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from oden.s7_watcher import (
    main as s7_main,
)
from oden.signal_listener import (
    subscribe_and_listen,
)
from oden.signal_manager import SignalManager, build_signal_cli_command, is_signal_cli_running


class TestS7Watcher(unittest.IsolatedAsyncioTestCase):
    @patch("oden.s7_watcher._create_tray", return_value=None)
    @patch("oden.s7_watcher.is_configured", return_value=(True, None))
    @patch("oden.config.validate_signal_number", return_value=(True, None, []))
    @patch("oden.s7_watcher.WEB_ENABLED", False)
    @patch("oden.s7_watcher.UNMANAGED_SIGNAL_CLI", False)
    @patch("oden.s7_watcher.SignalManager")
    @patch("oden.s7_watcher.subscribe_and_listen", new_callable=AsyncMock)
    @patch("oden.s7_watcher.SIGNAL_NUMBER", "+1234567890")
    @patch("oden.s7_watcher.SIGNAL_CLI_HOST", "1.2.3.4")
    @patch("oden.s7_watcher.SIGNAL_CLI_PORT", 1234)
    def test_main_managed_success(
        self, mock_subscribe, mock_signal_manager_class, mock_validate, mock_is_configured, mock_tray
    ):
        """Tests main in managed mode with successful execution."""
        mock_manager_instance = mock_signal_manager_class.return_value

        with self.assertRaises(SystemExit) as cm:
            s7_main()

        self.assertEqual(cm.exception.code, 0)
        mock_signal_manager_class.assert_called_once_with("1.2.3.4", 1234)
        mock_manager_instance.start.assert_called_once()
        mock_subscribe.assert_called_once_with("1.2.3.4", 1234)
        # stop() is called both when the listener task finishes and in
        # the finally block (safety cleanup), so it may be called twice.
        self.assertGreaterEqual(mock_manager_instance.stop.call_count, 1)

    @patch("oden.s7_watcher._create_tray", return_value=None)
    @patch("oden.s7_watcher.is_configured", return_value=(True, None))
    @patch("oden.config.validate_signal_number", return_value=(True, None, []))
    @patch("oden.s7_watcher.WEB_ENABLED", False)
    @patch("oden.s7_watcher.UNMANAGED_SIGNAL_CLI", True)
    @patch("oden.s7_watcher.is_signal_cli_running", return_value=True)
    @patch("oden.s7_watcher.subscribe_and_listen", new_callable=AsyncMock)
    @patch("oden.s7_watcher.SIGNAL_NUMBER", "+1234567890")
    @patch("oden.s7_watcher.SIGNAL_CLI_HOST", "1.2.3.4")
    @patch("oden.s7_watcher.SIGNAL_CLI_PORT", 1234)
    def test_main_unmanaged_success(
        self, mock_subscribe, mock_is_running, mock_validate, mock_is_configured, mock_tray
    ):
        """Tests main in unmanaged mode with signal-cli already running."""
        with self.assertRaises(SystemExit) as cm:
            s7_main()

        self.assertEqual(cm.exception.code, 0)
        mock_is_running.assert_called_once_with("1.2.3.4", 1234)
        mock_subscribe.assert_called_once_with("1.2.3.4", 1234)

    @patch("oden.s7_watcher._create_tray", return_value=None)
    @patch("oden.s7_watcher.is_configured", return_value=(True, None))
    @patch("oden.config.validate_signal_number", return_value=(True, None, []))
    @patch("oden.s7_watcher.WEB_ENABLED", False)
    @patch("oden.s7_watcher.UNMANAGED_SIGNAL_CLI", True)
    @patch("oden.s7_watcher.is_signal_cli_running", return_value=False)
    @patch("oden.s7_watcher.SIGNAL_NUMBER", "+1234567890")
    @patch("oden.s7_watcher.SIGNAL_CLI_HOST", "1.2.3.4")
    @patch("oden.s7_watcher.SIGNAL_CLI_PORT", 1234)
    def test_main_unmanaged_not_running(self, mock_is_running, mock_validate, mock_is_configured, mock_tray):
        """Tests main in unmanaged mode when signal-cli is not running."""
        with self.assertLogs("oden.s7_watcher", level="ERROR") as log:
            with self.assertRaises(SystemExit) as cm:
                s7_main()

            self.assertTrue(any("signal-cli is not running" in message for message in log.output))
        self.assertEqual(cm.exception.code, 0)

    @patch("asyncio.open_connection", side_effect=ConnectionRefusedError)
    async def test_subscribe_and_listen_connection_refused(self, mock_open_connection):
        """Tests that a connection refusal is handled gracefully and re-raised."""
        with self.assertLogs("oden.signal_listener", level="ERROR") as log:
            with self.assertRaises(ConnectionRefusedError):
                await subscribe_and_listen("host", 1234)

            self.assertTrue(any("Connection to signal-cli daemon failed" in message for message in log.output))
        mock_open_connection.assert_awaited_once_with("host", 1234, limit=ANY)


@patch("oden.signal_manager.find_signal_cli_executable", return_value="exec/path")
class TestSignalManager(unittest.TestCase):
    @patch("oden.config.SIGNAL_CLI_PATH", "/config/path/signal-cli")
    @patch("os.path.exists", return_value=True)
    def test_find_executable_from_config(self, mock_exists, mock_find_executable):
        """Tests finding executable from config path."""
        with patch("oden.signal_manager.find_signal_cli_executable", return_value="/config/path/signal-cli"):
            manager = SignalManager("host", "port")
            self.assertEqual(manager.executable, "/config/path/signal-cli")

    @patch("oden.config.SIGNAL_CLI_PATH", None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    def test_find_executable_from_path(self, mock_which, mock_find_executable):
        """Tests finding executable from system PATH."""
        with patch("oden.signal_manager.find_signal_cli_executable", return_value="/usr/bin/signal-cli"):
            manager = SignalManager("host", "port")
            self.assertEqual(manager.executable, "/usr/bin/signal-cli")

    @patch("oden.config.SIGNAL_CLI_PATH", None)
    @patch("shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("os.path.abspath", return_value="/bundled/signal-cli")
    def test_find_executable_bundled(self, mock_abspath, mock_exists, mock_which, mock_find_executable):
        """Tests finding the bundled executable."""
        with patch("oden.signal_manager.find_signal_cli_executable", return_value="/bundled/signal-cli"):
            manager = SignalManager("host", "port")
            self.assertEqual(manager.executable, "/bundled/signal-cli")

    @patch("oden.signal_manager.is_signal_cli_running", return_value=False)
    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_start_success(self, mock_sleep, mock_popen, mock_is_running, mock_find_executable):
        """Tests the successful start of the signal-cli daemon."""
        mock_is_running.side_effect = [False] * 5 + [True]  # Become available after 5s
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        manager = SignalManager("host", 1234)
        manager.start()

        mock_popen.assert_called_once()
        self.assertEqual(mock_is_running.call_count, 6)

    @patch("oden.signal_manager.is_signal_cli_running", return_value=True)
    def test_start_already_running(self, mock_is_running, mock_find_executable):
        """Tests that start does nothing if process is already running."""
        manager = SignalManager("host", 1234)
        with patch("subprocess.Popen") as mock_popen:
            manager.start()
            mock_popen.assert_not_called()

    @patch("oden.signal_manager.get_bundled_java_path", return_value=r"C:\\bundle\\jre-x64\\bin\\java.exe")
    def test_build_signal_cli_command_windows_prefers_java_for_install_dir(self, mock_java, mock_find_executable):
        """Windows should launch the bundled install directory through java.exe."""
        executable = "C:/bundle/signal-cli/bin/signal-cli"

        with (
            patch("oden.signal_manager.sys.platform", "win32"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            command = build_signal_cli_command(executable, ["link", "-n", "Oden"])

        self.assertEqual(
            command,
            [
                r"C:\\bundle\\jre-x64\\bin\\java.exe",
                "-cp",
                "C:/bundle/signal-cli/lib/*",
                "org.asamk.signal.Main",
                "link",
                "-n",
                "Oden",
            ],
        )

    @patch("oden.signal_manager.get_bundled_java_path", return_value=None)
    def test_build_signal_cli_command_windows_uses_bat_wrapper_without_java(self, mock_java, mock_find_executable):
        """Windows should fall back to cmd.exe for .bat launchers when Java is not bundled."""
        executable = r"C:\\bundle\\signal-cli\\bin\\signal-cli.bat"

        with patch("oden.signal_manager.sys.platform", "win32"):
            command = build_signal_cli_command(executable, ["daemon"])

        self.assertEqual(command, ["cmd.exe", "/c", executable, "daemon"])

    def test_get_standard_signal_cli_paths_windows_includes_home_share_path(self, mock_find_executable):
        """Windows installs may store accounts under ~/.local/share/signal-cli."""
        from pathlib import Path

        from oden.signal_manager import _get_standard_signal_cli_paths

        with (
            patch("oden.signal_manager.sys.platform", "win32"),
            patch.dict("oden.signal_manager.os.environ", {"LOCALAPPDATA": r"C:\\Users\\Nicklas\\AppData\\Local"}),
            patch("oden.signal_manager.Path.home", return_value=Path(r"C:\\Users\\Nicklas")),
        ):
            paths = _get_standard_signal_cli_paths()

        self.assertEqual(
            paths,
            [
                Path(r"C:\\Users\\Nicklas\\AppData\\Local") / "signal-cli",
                Path(r"C:\\Users\\Nicklas") / ".local" / "share" / "signal-cli",
            ],
        )


class TestIsSignalCliRunning(unittest.TestCase):
    @patch("socket.socket")
    def test_is_running_success(self, mock_socket):
        """Tests is_signal_cli_running when connection succeeds."""
        mock_sock_instance = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance
        mock_sock_instance.connect.return_value = True
        self.assertTrue(is_signal_cli_running("host", "port"))

    @patch("socket.socket")
    def test_is_running_failure(self, mock_socket):
        """Tests is_signal_cli_running when connection fails."""
        mock_sock_instance = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance
        mock_sock_instance.connect.side_effect = socket.error
        self.assertFalse(is_signal_cli_running("host", "port"))


class TestSignalLinkerInvalidACI(unittest.IsolatedAsyncioTestCase):
    """Tests for SignalLinker Invalid ACI error handling."""

    @patch("oden.signal_manager.get_bundled_signal_cli_path", return_value=None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    async def test_wait_for_link_invalid_aci_shows_friendly_error(self, mock_which, mock_bundled):
        """Tests that Invalid ACI error produces a user-friendly error message."""
        from oden.signal_linker import SignalLinker

        linker = SignalLinker(device_name="Test")

        # Create a mock process that simulates the Invalid ACI error
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (
            b"",
            b"java.lang.IllegalArgumentException: Invalid ACI!\n"
            b"at org.signal.core.models.ServiceId$ACI$Companion.parseOrThrow(ServiceId.kt:164)",
        )
        linker.process = mock_process

        result = await linker.wait_for_link(timeout=5.0)

        self.assertFalse(result)
        self.assertEqual(linker.status, "error")
        self.assertIn("signal-cli", linker.error)
        self.assertIn("0.14.0", linker.error)
        self.assertNotIn("IllegalArgumentException", linker.error)

    @patch("oden.signal_manager.get_bundled_signal_cli_path", return_value=None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    async def test_wait_for_link_other_error_shows_raw_message(self, mock_which, mock_bundled):
        """Tests that non-ACI errors show the raw error message."""
        from oden.signal_linker import SignalLinker

        linker = SignalLinker(device_name="Test")

        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (
            b"",
            b"Some other error occurred",
        )
        linker.process = mock_process

        result = await linker.wait_for_link(timeout=5.0)

        self.assertFalse(result)
        self.assertEqual(linker.status, "error")
        self.assertEqual(linker.error, "Some other error occurred")

    @patch("oden.signal_linker.get_existing_accounts")
    @patch("oden.signal_manager.get_bundled_signal_cli_path", return_value=None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    async def test_wait_for_link_recovers_number_from_accounts(
        self,
        mock_which,
        mock_bundled,
        mock_get_existing_accounts,
    ):
        """Successful links should recover the number from accounts.json when stdout omits it."""
        from oden.signal_linker import SignalLinker

        mock_get_existing_accounts.return_value = [
            {"number": "+46701111111"},
            {"number": "+46702222222"},
        ]

        linker = SignalLinker(device_name="Test")
        linker._accounts_before = {"+46701111111"}

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (
            b"Device linked successfully\n",
            b"",
        )
        linker.process = mock_process

        result = await linker.wait_for_link(timeout=5.0)

        self.assertTrue(result)
        self.assertEqual(linker.status, "linked")
        self.assertEqual(linker.linked_number, "+46702222222")


class TestSignalLinkerStartLink(unittest.IsolatedAsyncioTestCase):
    """Tests for SignalLinker.start_link() multi-line URI detection."""

    @patch("oden.signal_manager.get_bundled_signal_cli_path", return_value=None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    async def test_start_link_uri_on_first_line(self, mock_which, mock_bundled):
        """Tests that a URI on the first line is detected."""
        from oden.signal_linker import SignalLinker

        linker = SignalLinker(device_name="Test")
        uri = "sgnl://linkdevice?uuid=abc123&pub_key=xyz"

        mock_process = AsyncMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(return_value=f"{uri}\n".encode())
        mock_process.stdout = mock_stdout
        mock_process.stderr = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await linker.start_link()

        self.assertEqual(result, uri)
        self.assertEqual(linker.link_uri, uri)
        self.assertEqual(linker.status, "waiting")

    @patch("oden.signal_manager.get_bundled_signal_cli_path", return_value=None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    async def test_start_link_uri_after_warnings(self, mock_which, mock_bundled):
        """Tests that a URI is found even after warning lines."""
        from oden.signal_linker import SignalLinker

        linker = SignalLinker(device_name="Test")
        uri = "sgnl://linkdevice?uuid=abc123&pub_key=xyz"

        lines = [
            b"WARNING: Using incubator modules\n",
            b"Mar 15, 2026 12:00:00 INFO: Initializing\n",
            f"{uri}\n".encode(),
        ]
        call_count = 0

        async def mock_readline():
            nonlocal call_count
            if call_count < len(lines):
                line = lines[call_count]
                call_count += 1
                return line
            return b""

        mock_process = AsyncMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = mock_readline
        mock_process.stdout = mock_stdout
        mock_process.stderr = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await linker.start_link()

        self.assertEqual(result, uri)
        self.assertEqual(linker.link_uri, uri)

    @patch("oden.signal_manager.get_bundled_signal_cli_path", return_value=None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    async def test_start_link_no_uri_eof(self, mock_which, mock_bundled):
        """Tests error when signal-cli exits without producing a URI."""
        from oden.signal_linker import SignalLinker

        linker = SignalLinker(device_name="Test")

        lines = [b"Some warning text\n", b""]
        call_count = 0

        async def mock_readline():
            nonlocal call_count
            if call_count < len(lines):
                line = lines[call_count]
                call_count += 1
                return line
            return b""

        mock_process = AsyncMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = mock_readline
        mock_process.stdout = mock_stdout
        mock_stderr = AsyncMock()
        stderr_lines = [b"Error: something went wrong\n", b""]
        stderr_call = 0

        async def mock_stderr_readline():
            nonlocal stderr_call
            if stderr_call < len(stderr_lines):
                line = stderr_lines[stderr_call]
                stderr_call += 1
                return line
            return b""

        mock_stderr.readline = mock_stderr_readline
        mock_process.stderr = mock_stderr

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await linker.start_link()

        self.assertIsNone(result)
        self.assertEqual(linker.status, "error")
        self.assertIn("signal-cli", linker.error)
        # Should include stderr in error message
        self.assertIn("something went wrong", linker.error)

    @patch("oden.signal_manager.get_bundled_signal_cli_path", return_value=None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    async def test_start_link_no_uri_no_stderr(self, mock_which, mock_bundled):
        """Tests error when signal-cli exits without URI and no stderr."""
        from oden.signal_linker import SignalLinker

        linker = SignalLinker(device_name="Test")

        mock_process = AsyncMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(return_value=b"")
        mock_process.stdout = mock_stdout
        mock_stderr = AsyncMock()
        mock_stderr.readline = AsyncMock(return_value=b"")
        mock_process.stderr = mock_stderr

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await linker.start_link()

        self.assertIsNone(result)
        self.assertEqual(linker.status, "error")
        self.assertIn("signal-cli", linker.error)

    @patch("oden.signal_manager.get_bundled_signal_cli_path", return_value=None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    async def test_start_link_uri_embedded_in_log_line(self, mock_which, mock_bundled):
        """URI embedded in a log line (e.g. 'INFO LinkCommand - sgnl://...')."""
        from oden.signal_linker import SignalLinker

        linker = SignalLinker(device_name="Test")
        uri = "sgnl://linkdevice?uuid=abc123&pub_key=xyz"

        mock_process = AsyncMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(return_value=f"INFO LinkCommand - {uri}\n".encode())
        mock_process.stdout = mock_stdout
        mock_process.stderr = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await linker.start_link()

        self.assertEqual(result, uri)
        self.assertEqual(linker.link_uri, uri)

    @patch("oden.signal_manager.get_bundled_signal_cli_path", return_value=None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    async def test_start_link_uri_found_on_stderr(self, mock_which, mock_bundled):
        """URI found on stderr when stdout has no URI."""
        from oden.signal_linker import SignalLinker

        linker = SignalLinker(device_name="Test")
        uri = "sgnl://linkdevice?uuid=abc123&pub_key=xyz"

        stdout_lines = [b"Some warning\n", b""]
        stdout_call = 0

        async def mock_stdout_readline():
            nonlocal stdout_call
            if stdout_call < len(stdout_lines):
                line = stdout_lines[stdout_call]
                stdout_call += 1
                return line
            return b""

        stderr_lines = [b"DEBUG log line\n", f"{uri}\n".encode(), b""]
        stderr_call = 0

        async def mock_stderr_readline():
            nonlocal stderr_call
            if stderr_call < len(stderr_lines):
                line = stderr_lines[stderr_call]
                stderr_call += 1
                return line
            return b""

        mock_process = AsyncMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = mock_stdout_readline
        mock_process.stdout = mock_stdout
        mock_stderr = AsyncMock()
        mock_stderr.readline = mock_stderr_readline
        mock_process.stderr = mock_stderr

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await linker.start_link()

        self.assertEqual(result, uri)
        self.assertEqual(linker.link_uri, uri)


class TestAppStateContacts(unittest.TestCase):
    """Tests for AppState contact cache and name resolution."""

    def test_update_contacts_builds_dict_by_number(self):
        from oden.app_state import AppState

        state = AppState()
        contacts = [
            {"number": "+46701234567", "name": "Alice"},
            {"number": "+46709876543", "name": "Bob"},
            {"number": None, "name": "NoNumber"},  # should be skipped
        ]
        state.update_contacts(contacts)
        self.assertEqual(len(state.contacts), 2)
        self.assertEqual(state.contacts["+46701234567"]["name"], "Alice")
        self.assertEqual(state.contacts["+46709876543"]["name"], "Bob")

    def test_resolve_contact_name_uses_envelope_name_first(self):
        from oden.app_state import AppState

        state = AppState()
        state.update_contacts([{"number": "+46701234567", "name": "Alice"}])
        # Envelope name takes priority
        result = state.resolve_contact_name("+46701234567", "EnvelopeName")
        self.assertEqual(result, "EnvelopeName")

    def test_resolve_contact_name_falls_back_to_contact(self):
        from oden.app_state import AppState

        state = AppState()
        state.update_contacts([{"number": "+46701234567", "name": "Alice"}])
        # When envelope name equals the number, fall back to contact name
        result = state.resolve_contact_name("+46701234567", "+46701234567")
        self.assertEqual(result, "Alice")

    def test_resolve_contact_name_falls_back_to_contact_when_none(self):
        from oden.app_state import AppState

        state = AppState()
        state.update_contacts([{"number": "+46701234567", "name": "Alice"}])
        result = state.resolve_contact_name("+46701234567", None)
        self.assertEqual(result, "Alice")

    def test_resolve_contact_name_returns_okand_when_no_match(self):
        from oden.app_state import AppState

        state = AppState()
        result = state.resolve_contact_name("+46700000000", None)
        self.assertEqual(result, "Okänd")

    def test_resolve_contact_name_uses_nickname(self):
        from oden.app_state import AppState

        state = AppState()
        state.update_contacts([{"number": "+46701234567", "nickName": "Nicke"}])
        result = state.resolve_contact_name("+46701234567", None)
        self.assertEqual(result, "Nicke")


class TestResolveSignalDataPath(unittest.TestCase):
    """Tests for resolve_signal_data_path() — standard location fallback."""

    def test_uses_oden_path_when_accounts_exist(
        self,
    ):
        """When SIGNAL_DATA_PATH has accounts.json, use it."""
        import tempfile
        from pathlib import Path

        from oden.signal_manager import resolve_signal_data_path

        with tempfile.TemporaryDirectory() as tmpdir:
            oden_dir = Path(tmpdir) / "oden-signal-data"
            accounts_dir = oden_dir / "data"
            accounts_dir.mkdir(parents=True)
            (accounts_dir / "accounts.json").write_text('{"accounts": []}')

            with patch("oden.signal_manager.cfg.SIGNAL_DATA_PATH", oden_dir):
                result = resolve_signal_data_path()
                self.assertEqual(result, oden_dir)

    def test_falls_back_to_standard_when_oden_empty(self):
        """When SIGNAL_DATA_PATH has no accounts, fall back to standard location."""
        import tempfile
        from pathlib import Path

        from oden.signal_manager import resolve_signal_data_path

        with tempfile.TemporaryDirectory() as tmpdir:
            oden_dir = Path(tmpdir) / "oden-signal-data"
            oden_dir.mkdir()
            std_dir = Path(tmpdir) / "standard-signal-cli"
            (std_dir / "data").mkdir(parents=True)
            (std_dir / "data" / "accounts.json").write_text('{"accounts": []}')

            with (
                patch("oden.signal_manager.cfg.SIGNAL_DATA_PATH", oden_dir),
                patch(
                    "oden.signal_manager._get_standard_signal_cli_paths",
                    return_value=[std_dir],
                ),
            ):
                result = resolve_signal_data_path()
                self.assertEqual(result, std_dir)

    def test_returns_oden_path_when_no_accounts_anywhere(self):
        """When no accounts exist anywhere, return SIGNAL_DATA_PATH."""
        import tempfile
        from pathlib import Path

        from oden.signal_manager import resolve_signal_data_path

        with tempfile.TemporaryDirectory() as tmpdir:
            oden_dir = Path(tmpdir) / "oden-signal-data"
            oden_dir.mkdir()

            with (
                patch("oden.signal_manager.cfg.SIGNAL_DATA_PATH", oden_dir),
                patch(
                    "oden.signal_manager._get_standard_signal_cli_paths",
                    return_value=[],
                ),
            ):
                result = resolve_signal_data_path()
                self.assertEqual(result, oden_dir)


if __name__ == "__main__":
    unittest.main()
