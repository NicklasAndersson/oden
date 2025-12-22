import unittest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock
import config
import importlib
import io
import warnings
import sys

# Import the main function and necessary configurations
from s7_watcher import subscribe_and_listen, SIGNAL_RPC_HOST, SIGNAL_RPC_PORT
from processing import process_message

class TestS7Watcher(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Ignore RuntimeWarning for unawaited coroutines in mocks globally for the class
        warnings.simplefilter('ignore', RuntimeWarning)

    @classmethod
    def tearDownClass(cls):
        # Reset warnings filter globally after the class tests
        warnings.resetwarnings()
    def setUp(self):
        # Patch config.get_config to return a dummy configuration
        self.patcher_get_config = patch('config.get_config')
        self.mock_get_config = self.patcher_get_config.start()
        self.mock_get_config.return_value = {
            'vault_path': 'mock_vault',
            'inbox_path': 'mock_inbox',
            'signal_number': 'mock_signal_number'
        }
        # Reload config module to apply the mock
        import config
        import importlib
        importlib.reload(config)

        # Patch the module-level variables in s7_watcher that import from config
        self.patcher_vault_path = patch('s7_watcher.VAULT_PATH', 'mock_vault')
        self.patcher_inbox_path = patch('s7_watcher.INBOX_PATH', 'mock_inbox')
        self.patcher_signal_number = patch('s7_watcher.SIGNAL_NUMBER', 'mock_signal_number')

        self.patcher_vault_path.start()
        self.patcher_inbox_path.start()
        self.patcher_signal_number.start()

        # Patch sys.stderr
        self.patcher_stderr = patch('sys.stderr', new_callable=io.StringIO)
        self.mock_stderr = self.patcher_stderr.start()


    def tearDown(self):
        self.patcher_get_config.stop()
        self.patcher_vault_path.stop()
        self.patcher_inbox_path.stop()
        self.patcher_signal_number.stop()
        self.patcher_stderr.stop()

        # Reload config module again to clean up the mock
        import config
        import importlib
        importlib.reload(config)

    @patch('asyncio.open_connection', side_effect=ConnectionRefusedError)
    @patch('sys.exit')
    async def test_subscribe_and_listen_connection_refused(self, mock_exit, mock_open_connection):
        await subscribe_and_listen()

        mock_open_connection.assert_awaited_once_with(SIGNAL_RPC_HOST, SIGNAL_RPC_PORT, limit=unittest.mock.ANY)
        self.assertIn("Connection to signal-cli daemon failed:", self.mock_stderr.getvalue())
        mock_exit.assert_called_once_with(1) # Ensure sys.exit(1) was called

    # Add test for json decode error
    @patch('asyncio.open_connection')
    async def test_subscribe_and_listen_json_decode_error(self, mock_open_connection):
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        # Mock reader.at_eof as a non-async callable
        mock_reader.at_eof = MagicMock(side_effect=[False, True])
        mock_reader.readline.side_effect = [
            b'this is not json\n',
            b'', # EOF
        ]

        await subscribe_and_listen()

        self.assertIn("ERROR: Received non-JSON message:", self.mock_stderr.getvalue())

    # Add test for general exception during message processing
    @patch('asyncio.open_connection')
    @patch('s7_watcher.process_message', side_effect=Exception("Processing error"))
    async def test_subscribe_and_listen_processing_exception(self, mock_process_message, mock_open_connection):
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        # Mock reader.at_eof as a non-async callable
        mock_reader.at_eof = MagicMock(side_effect=[False, True])
        mock_reader.readline.side_effect = [
            json.dumps({"jsonrpc": "2.0", "method": "receive", "params": {"envelope": {"source": "+123", "dataMessage": {"message": "Hello"}}}}) 
            .encode('utf-8') + b'\n',
            b'', # EOF
        ]

        await subscribe_and_listen()

        mock_process_message.assert_awaited_once()
        self.assertIn("ERROR: Could not process message.", self.mock_stderr.getvalue())

if __name__ == '__main__':
    unittest.main()
