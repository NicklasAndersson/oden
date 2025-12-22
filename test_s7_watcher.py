import asyncio
import io
import json
import unittest
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import config
import importlib

from s7_watcher import SIGNAL_RPC_HOST, SIGNAL_RPC_PORT, subscribe_and_listen

class TestS7Watcher(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Ignore RuntimeWarning for unawaited coroutines in mocks
        warnings.simplefilter('ignore', RuntimeWarning)

    @classmethod
    def tearDownClass(cls):
        # Reset warnings filter after class tests
        warnings.resetwarnings()

    def setUp(self):
        # Mock configuration
        self.patcher_get_config = patch('config.get_config')
        self.mock_get_config = self.patcher_get_config.start()
        self.mock_get_config.return_value = {
            'vault_path': 'mock_vault'
        }
        importlib.reload(config)

        # Patch module-level variables
        self.patcher_vault_path = patch('s7_watcher.VAULT_PATH', 'mock_vault')
        self.patcher_stderr = patch('sys.stderr', new_callable=io.StringIO)

        self.patcher_vault_path.start()
        self.mock_stderr = self.patcher_stderr.start()


    def tearDown(self):
        self.patcher_get_config.stop()
        self.patcher_vault_path.stop()
        self.patcher_stderr.stop()
        importlib.reload(config)

    @patch('asyncio.open_connection', side_effect=ConnectionRefusedError)
    @patch('sys.exit')
    async def test_subscribe_and_listen_connection_refused(self, mock_exit, mock_open_connection):
        await subscribe_and_listen()

        mock_open_connection.assert_awaited_once_with(SIGNAL_RPC_HOST, SIGNAL_RPC_PORT, limit=unittest.mock.ANY)
        self.assertIn("Connection to signal-cli daemon failed:", self.mock_stderr.getvalue())
        mock_exit.assert_called_once_with(1)

    @patch('asyncio.open_connection')
    async def test_subscribe_and_listen_json_decode_error(self, mock_open_connection):
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        mock_reader.at_eof = MagicMock(side_effect=[False, True])
        mock_reader.readline.side_effect = [
            b'this is not json\n',
            b'',
        ]

        await subscribe_and_listen()

        self.assertIn("ERROR: Received non-JSON message:", self.mock_stderr.getvalue())

    @patch('asyncio.open_connection')
    @patch('s7_watcher.process_message', side_effect=Exception("Processing error"))
    async def test_subscribe_and_listen_processing_exception(self, mock_process_message, mock_open_connection):
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        mock_reader.at_eof = MagicMock(side_effect=[False, True])
        message = json.dumps({
            "jsonrpc": "2.0",
            "method": "receive",
            "params": {
                "envelope": {
                    "source": "+123",
                    "dataMessage": {"message": "Hello"}
                }
            }
        })
        mock_reader.readline.side_effect = [
            message.encode('utf-8') + b'\n',
            b'',
        ]

        await subscribe_and_listen()

        mock_process_message.assert_awaited_once()
        self.assertIn("ERROR: Could not process message.", self.mock_stderr.getvalue())

if __name__ == '__main__':
    unittest.main()
