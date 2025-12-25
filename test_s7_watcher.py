import asyncio
import io
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from s7_watcher import (
    SIGNAL_RPC_HOST,
    SIGNAL_RPC_PORT,
    subscribe_and_listen,
    main as s7_main,
    SignalManager
)

class TestS7Watcher(unittest.IsolatedAsyncioTestCase):

    @patch('s7_watcher.SignalManager')
    @patch('s7_watcher.subscribe_and_listen', new_callable=AsyncMock)
    @patch('s7_watcher.SIGNAL_NUMBER', '+1234567890')
    def test_main_success(self, mock_subscribe, mock_signal_manager_class):
        """Tests that main starts SignalManager and runs the async loop."""
        mock_manager_instance = mock_signal_manager_class.return_value
        
        with self.assertRaises(SystemExit) as cm:
            s7_main()

        self.assertEqual(cm.exception.code, 0)
        mock_signal_manager_class.assert_called_once_with('+1234567890', SIGNAL_RPC_HOST, SIGNAL_RPC_PORT)
        mock_manager_instance.start.assert_called_once()
        mock_subscribe.assert_called_once()
        mock_manager_instance.stop.assert_called_once()

    @patch('asyncio.open_connection', side_effect=ConnectionRefusedError)
    @patch('sys.exit', side_effect=SystemExit)
    @patch('sys.stderr', new_callable=io.StringIO)
    async def test_subscribe_and_listen_connection_refused(self, mock_stderr, mock_exit, mock_open_connection):
        """Tests that a connection refusal is handled gracefully and exits."""
        with self.assertRaises(SystemExit):
            await subscribe_and_listen()
        mock_open_connection.assert_awaited_once_with(SIGNAL_RPC_HOST, SIGNAL_RPC_PORT, limit=unittest.mock.ANY)
        self.assertIn("Connection to signal-cli daemon failed:", mock_stderr.getvalue())
        mock_exit.assert_called_once_with(1)

    @patch('asyncio.open_connection')
    @patch('s7_watcher.process_message', new_callable=AsyncMock)
    async def test_subscribe_and_listen_success(self, mock_process_message, mock_open_connection):
        """Tests the happy path: connect, receive a message, and process it."""
        mock_reader = MagicMock()
        mock_reader.at_eof = MagicMock(side_effect=[False, True])
        message = {"method": "receive", "params": {"foo": "bar"}}
        mock_reader.readline = AsyncMock(side_effect=[json.dumps(message).encode('utf-8') + b'\n'])
        
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        await subscribe_and_listen()

        mock_process_message.assert_awaited_once_with({"foo": "bar"}, mock_reader, mock_writer)
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()

    @patch('asyncio.open_connection')
    @patch('sys.stderr', new_callable=io.StringIO)
    async def test_subscribe_and_listen_json_decode_error(self, mock_stderr, mock_open_connection):
        """Tests that a non-JSON message is handled correctly."""
        mock_reader = MagicMock()
        mock_reader.at_eof = MagicMock(side_effect=[False, True])
        mock_reader.readline = AsyncMock(side_effect=[b'this is not json\n'])
        
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        await subscribe_and_listen()

        self.assertIn("ERROR: Received non-JSON message:", mock_stderr.getvalue())

    @patch('asyncio.open_connection')
    @patch('s7_watcher.process_message', new_callable=AsyncMock, side_effect=Exception("Processing error"))
    @patch('sys.stderr', new_callable=io.StringIO)
    async def test_subscribe_and_listen_processing_exception(self, mock_stderr, mock_process_message, mock_open_connection):
        """Tests that an exception during message processing is caught and logged."""
        mock_reader = MagicMock()
        mock_reader.at_eof = MagicMock(side_effect=[False, True])
        message = {"method": "receive", "params": {"envelope": "some_data"}}
        mock_reader.readline = AsyncMock(side_effect=[json.dumps(message).encode('utf-8') + b'\n'])
        
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        await subscribe_and_listen()

        mock_process_message.assert_awaited_once()
        self.assertIn("ERROR: Could not process message.", mock_stderr.getvalue())

if __name__ == '__main__':
    unittest.main()