import asyncio
import io
import json
import socket
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from s7_watcher import (
    subscribe_and_listen,
    main as s7_main,
    SignalManager,
    is_signal_cli_running
)

class TestS7Watcher(unittest.IsolatedAsyncioTestCase):

    @patch('s7_watcher.UNMANAGED_SIGNAL_CLI', False)
    @patch('s7_watcher.SignalManager')
    @patch('s7_watcher.subscribe_and_listen', new_callable=AsyncMock)
    @patch('s7_watcher.SIGNAL_NUMBER', '+1234567890')
    @patch('s7_watcher.SIGNAL_CLI_HOST', '1.2.3.4')
    @patch('s7_watcher.SIGNAL_CLI_PORT', 1234)
    def test_main_managed_success(self, mock_subscribe, mock_signal_manager_class):
        """Tests main in managed mode with successful execution."""
        mock_manager_instance = mock_signal_manager_class.return_value
        
        with self.assertRaises(SystemExit) as cm:
            s7_main()

        self.assertEqual(cm.exception.code, 0)
        mock_signal_manager_class.assert_called_once_with('+1234567890', '1.2.3.4', 1234)
        mock_manager_instance.start.assert_called_once()
        mock_subscribe.assert_called_once_with('1.2.3.4', 1234)
        mock_manager_instance.stop.assert_called_once()

    @patch('s7_watcher.UNMANAGED_SIGNAL_CLI', True)
    @patch('s7_watcher.is_signal_cli_running', return_value=True)
    @patch('s7_watcher.subscribe_and_listen', new_callable=AsyncMock)
    @patch('s7_watcher.SIGNAL_NUMBER', '+1234567890')
    @patch('s7_watcher.SIGNAL_CLI_HOST', '1.2.3.4')
    @patch('s7_watcher.SIGNAL_CLI_PORT', 1234)
    def test_main_unmanaged_success(self, mock_subscribe, mock_is_running):
        """Tests main in unmanaged mode with signal-cli already running."""
        with self.assertRaises(SystemExit) as cm:
            s7_main()
        
        self.assertEqual(cm.exception.code, 0)
        mock_is_running.assert_called_once_with('1.2.3.4', 1234)
        mock_subscribe.assert_called_once_with('1.2.3.4', 1234)

    @patch('s7_watcher.UNMANAGED_SIGNAL_CLI', True)
    @patch('s7_watcher.is_signal_cli_running', return_value=False)
    @patch('sys.exit', side_effect=SystemExit)
    @patch('sys.stderr', new_callable=io.StringIO)
    @patch('s7_watcher.SIGNAL_NUMBER', '+1234567890')
    def test_main_unmanaged_not_running(self, mock_stderr, mock_exit, mock_is_running):
        """Tests main in unmanaged mode when signal-cli is not running."""
        with self.assertRaises(SystemExit):
            s7_main()
        
        self.assertIn("signal-cli is not running", mock_stderr.getvalue())
        mock_exit.assert_called_once_with(1)

    @patch('asyncio.open_connection', side_effect=ConnectionRefusedError)
    @patch('sys.exit', side_effect=SystemExit)
    @patch('sys.stderr', new_callable=io.StringIO)
    async def test_subscribe_and_listen_connection_refused(self, mock_stderr, mock_exit, mock_open_connection):
        """Tests that a connection refusal is handled gracefully and exits."""
        with self.assertRaises(SystemExit):
            await subscribe_and_listen('host', 1234)
        mock_open_connection.assert_awaited_once_with('host', 1234, limit=ANY)
        self.assertIn("Connection to signal-cli daemon failed:", mock_stderr.getvalue())
        mock_exit.assert_called_once_with(1)

class TestSignalManager(unittest.TestCase):

    @patch('s7_watcher.SIGNAL_CLI_PATH', '/config/path/signal-cli')
    @patch('os.path.exists', return_value=True)
    def test_find_executable_from_config(self, mock_exists):
        """Tests finding executable from config path."""
        manager = SignalManager('num', 'host', 'port')
        self.assertEqual(manager.executable, '/config/path/signal-cli')

    @patch('s7_watcher.SIGNAL_CLI_PATH', None)
    @patch('shutil.which', return_value='/usr/bin/signal-cli')
    def test_find_executable_from_path(self, mock_which):
        """Tests finding executable from system PATH."""
        manager = SignalManager('num', 'host', 'port')
        self.assertEqual(manager.executable, '/usr/bin/signal-cli')

    @patch('s7_watcher.SIGNAL_CLI_PATH', None)
    @patch('shutil.which', return_value=None)
    @patch('os.path.exists', return_value=True)
    @patch('os.path.abspath', return_value='/bundled/signal-cli')
    def test_find_executable_bundled(self, mock_abspath, mock_exists, mock_which):
        """Tests finding the bundled executable."""
        manager = SignalManager('num', 'host', 'port')
        self.assertEqual(manager.executable, '/bundled/signal-cli')

    @patch('s7_watcher.is_signal_cli_running', return_value=False)
    @patch('subprocess.Popen')
    @patch('time.sleep')
    def test_start_success(self, mock_sleep, mock_popen, mock_is_running):
        """Tests the successful start of the signal-cli daemon."""
        mock_is_running.side_effect = [False] * 5 + [True] # Become available after 5s
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        
        manager = SignalManager('+123', 'host', 1234)
        manager.executable = 'exec/path'
        manager.start()

        mock_popen.assert_called_once()
        self.assertEqual(mock_is_running.call_count, 6)

    @patch('s7_watcher.is_signal_cli_running', return_value=True)
    def test_start_already_running(self, mock_is_running):
        """Tests that start does nothing if process is already running."""
        manager = SignalManager('+123', 'host', 1234)
        with patch('subprocess.Popen') as mock_popen:
            manager.start()
            mock_popen.assert_not_called()

class TestIsSignalCliRunning(unittest.TestCase):
    @patch('socket.socket')
    def test_is_running_success(self, mock_socket):
        """Tests is_signal_cli_running when connection succeeds."""
        mock_sock_instance = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance
        mock_sock_instance.connect.return_value = True
        self.assertTrue(is_signal_cli_running('host', 'port'))

    @patch('socket.socket')
    def test_is_running_failure(self, mock_socket):
        """Tests is_signal_cli_running when connection fails."""
        mock_sock_instance = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance
        mock_sock_instance.connect.side_effect = socket.error
        self.assertFalse(is_signal_cli_running('host', 'port'))

if __name__ == '__main__':
    unittest.main()