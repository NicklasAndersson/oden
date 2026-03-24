import socket
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from oden.s7_watcher import (
    main as s7_main,
)
from oden.signal_listener import (
    subscribe_and_listen,
)
from oden.signal_manager import SignalManager, is_signal_cli_running


class TestS7Watcher(unittest.IsolatedAsyncioTestCase):
    @patch("oden.s7_watcher._create_tray", return_value=None)
    @patch("oden.s7_watcher.is_configured", return_value=(True, None))
    @patch("oden.s7_watcher.WEB_ENABLED", False)
    @patch("oden.s7_watcher.UNMANAGED_SIGNAL_CLI", False)
    @patch("oden.s7_watcher.SignalManager")
    @patch("oden.s7_watcher.subscribe_and_listen", new_callable=AsyncMock)
    @patch("oden.s7_watcher.SIGNAL_NUMBER", "+1234567890")
    @patch("oden.s7_watcher.SIGNAL_CLI_HOST", "1.2.3.4")
    @patch("oden.s7_watcher.SIGNAL_CLI_PORT", 1234)
    def test_main_managed_success(self, mock_subscribe, mock_signal_manager_class, mock_is_configured, mock_tray):
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
    @patch("oden.s7_watcher.WEB_ENABLED", False)
    @patch("oden.s7_watcher.UNMANAGED_SIGNAL_CLI", True)
    @patch("oden.s7_watcher.is_signal_cli_running", return_value=True)
    @patch("oden.s7_watcher.subscribe_and_listen", new_callable=AsyncMock)
    @patch("oden.s7_watcher.SIGNAL_NUMBER", "+1234567890")
    @patch("oden.s7_watcher.SIGNAL_CLI_HOST", "1.2.3.4")
    @patch("oden.s7_watcher.SIGNAL_CLI_PORT", 1234)
    def test_main_unmanaged_success(self, mock_subscribe, mock_is_running, mock_is_configured, mock_tray):
        """Tests main in unmanaged mode with signal-cli already running."""
        with self.assertRaises(SystemExit) as cm:
            s7_main()

        self.assertEqual(cm.exception.code, 0)
        mock_is_running.assert_called_once_with("1.2.3.4", 1234)
        mock_subscribe.assert_called_once_with("1.2.3.4", 1234)

    @patch("oden.s7_watcher._create_tray", return_value=None)
    @patch("oden.s7_watcher.is_configured", return_value=(True, None))
    @patch("oden.s7_watcher.WEB_ENABLED", False)
    @patch("oden.s7_watcher.UNMANAGED_SIGNAL_CLI", True)
    @patch("oden.s7_watcher.is_signal_cli_running", return_value=False)
    @patch("oden.s7_watcher.SIGNAL_NUMBER", "+1234567890")
    @patch("oden.s7_watcher.SIGNAL_CLI_HOST", "1.2.3.4")
    @patch("oden.s7_watcher.SIGNAL_CLI_PORT", 1234)
    def test_main_unmanaged_not_running(self, mock_is_running, mock_is_configured, mock_tray):
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
        mock_stderr.read = AsyncMock(return_value=b"Error: something went wrong")
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
        mock_stderr.read = AsyncMock(return_value=b"")
        mock_process.stderr = mock_stderr

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await linker.start_link()

        self.assertIsNone(result)
        self.assertEqual(linker.status, "error")
        self.assertIn("signal-cli", linker.error)


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


if __name__ == "__main__":
    unittest.main()
