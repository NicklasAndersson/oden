import socket
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from oden.s7_watcher import (
    main as s7_main,
)
from oden.s7_watcher import (
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
        mock_signal_manager_class.assert_called_once_with("+1234567890", "1.2.3.4", 1234)
        mock_manager_instance.start.assert_called_once()
        mock_subscribe.assert_called_once_with("1.2.3.4", 1234)
        mock_manager_instance.stop.assert_called_once()

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
    @patch("oden.s7_watcher.UNMANAGED_SIGNAL_CLI", True)
    @patch("oden.s7_watcher.is_signal_cli_running", return_value=False)
    @patch("sys.exit", side_effect=SystemExit)
    @patch("oden.s7_watcher.SIGNAL_NUMBER", "+1234567890")
    def test_main_unmanaged_not_running(self, mock_exit, mock_is_running, mock_is_configured, mock_tray):
        """Tests main in unmanaged mode when signal-cli is not running."""
        with self.assertLogs("oden.s7_watcher", level="ERROR") as log:
            with self.assertRaises(SystemExit):
                s7_main()

            self.assertTrue(any("signal-cli is not running" in message for message in log.output))
        mock_exit.assert_called_once_with(1)

    @patch("asyncio.open_connection", side_effect=ConnectionRefusedError)
    async def test_subscribe_and_listen_connection_refused(self, mock_open_connection):
        """Tests that a connection refusal is handled gracefully and re-raised."""
        with self.assertLogs("oden.s7_watcher", level="ERROR") as log:
            with self.assertRaises(ConnectionRefusedError):
                await subscribe_and_listen("host", 1234)

            self.assertTrue(any("Connection to signal-cli daemon failed" in message for message in log.output))
        mock_open_connection.assert_awaited_once_with("host", 1234, limit=ANY)


@patch.object(SignalManager, "_find_executable", return_value="exec/path")
class TestSignalManager(unittest.TestCase):
    @patch("oden.config.SIGNAL_CLI_PATH", "/config/path/signal-cli")
    @patch("os.path.exists", return_value=True)
    def test_find_executable_from_config(self, mock_exists, mock_find_executable):
        """Tests finding executable from config path."""
        with patch.object(SignalManager, "_find_executable", new_callable=MagicMock) as mock_find:
            mock_find.return_value = "/config/path/signal-cli"
            manager = SignalManager("num", "host", "port")
            self.assertEqual(manager.executable, "/config/path/signal-cli")

    @patch("oden.config.SIGNAL_CLI_PATH", None)
    @patch("shutil.which", return_value="/usr/bin/signal-cli")
    def test_find_executable_from_path(self, mock_which, mock_find_executable):
        """Tests finding executable from system PATH."""
        with patch.object(SignalManager, "_find_executable", new_callable=MagicMock) as mock_find:
            mock_find.return_value = "/usr/bin/signal-cli"
            manager = SignalManager("num", "host", "port")
            self.assertEqual(manager.executable, "/usr/bin/signal-cli")

    @patch("oden.config.SIGNAL_CLI_PATH", None)
    @patch("shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("os.path.abspath", return_value="/bundled/signal-cli")
    def test_find_executable_bundled(self, mock_abspath, mock_exists, mock_which, mock_find_executable):
        """Tests finding the bundled executable."""
        with patch.object(SignalManager, "_find_executable", new_callable=MagicMock) as mock_find:
            mock_find.return_value = "/bundled/signal-cli"
            manager = SignalManager("num", "host", "port")
            self.assertEqual(manager.executable, "/bundled/signal-cli")

    @patch("oden.signal_manager.is_signal_cli_running", return_value=False)
    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_start_success(self, mock_sleep, mock_popen, mock_is_running, mock_find_executable):
        """Tests the successful start of the signal-cli daemon."""
        mock_is_running.side_effect = [False] * 5 + [True]  # Become available after 5s
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        manager = SignalManager("+123", "host", 1234)
        manager.start()

        mock_popen.assert_called_once()
        self.assertEqual(mock_is_running.call_count, 6)

    @patch("oden.signal_manager.is_signal_cli_running", return_value=True)
    def test_start_already_running(self, mock_is_running, mock_find_executable):
        """Tests that start does nothing if process is already running."""
        manager = SignalManager("+123", "host", 1234)
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


if __name__ == "__main__":
    unittest.main()
