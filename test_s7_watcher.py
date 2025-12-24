import asyncio
import io
import json
import socket
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from s7_watcher import (
    SIGNAL_RPC_HOST, 
    SIGNAL_RPC_PORT, 
    is_signal_cli_running,
    subscribe_and_listen,
    main as s7_main
)

class TestS7Watcher(unittest.IsolatedAsyncioTestCase):

    @patch('s7_watcher.is_signal_cli_running', return_value=True)
    @patch('s7_watcher.subscribe_and_listen')
    @patch('asyncio.run')
    def test_main_success(self, mock_asyncio_run, mock_subscribe, mock_is_running):
        """Tests that main runs the async loop if signal-cli is running."""
        s7_main()
        mock_is_running.assert_called_once()
        mock_asyncio_run.assert_called_once_with(mock_subscribe())

    @patch('s7_watcher.is_signal_cli_running', return_value=False)
    @patch('sys.exit')
    @patch('asyncio.run')
    def test_main_signal_cli_not_running(self, mock_asyncio_run, mock_exit, mock_is_running):
        """Tests that main exits if signal-cli is not running."""
        s7_main()
        mock_is_running.assert_called_once()
        mock_asyncio_run.assert_not_called()
        mock_exit.assert_called_once_with(1)

    @patch('socket.socket')
    def test_is_signal_cli_running(self, mock_socket):
        """Tests the is_signal_cli_running helper function."""
        # Case 1: Connection succeeds
        mock_socket.return_value.__enter__.return_value.connect.return_value = None
        self.assertTrue(is_signal_cli_running('host', 'port'))

        # Case 2: Connection fails
        mock_socket.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError
        self.assertFalse(is_signal_cli_running('host', 'port'))

    @patch('asyncio.open_connection', side_effect=ConnectionRefusedError)
    @patch('sys.exit')
    @patch('sys.stderr', new_callable=io.StringIO)
    async def test_subscribe_and_listen_connection_refused(self, mock_stderr, mock_exit, mock_open_connection):
        """Tests that a connection refusal is handled gracefully and exits."""
        await subscribe_and_listen()
        mock_open_connection.assert_awaited_once_with(SIGNAL_RPC_HOST, SIGNAL_RPC_PORT, limit=unittest.mock.ANY)
        self.assertIn("Connection to signal-cli daemon failed:", mock_stderr.getvalue())
        mock_exit.assert_called_once_with(1)
        
    @patch('asyncio.open_connection')
    @patch('s7_watcher.process_message')
    async def test_subscribe_and_listen_success(self, mock_process_message, mock_open_connection):
        """Tests the happy path: connect, receive a message, and process it."""
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        message = {
            "jsonrpc": "2.0",
            "method": "receive",
            "params": {"envelope": {"dataMessage": {"message": "Hello"}}}
        }
        # Simulate one message and then EOF
        mock_reader.at_eof.side_effect = [False, True]
        mock_reader.readline.side_effect = [json.dumps(message).encode('utf-8') + b'\n']

        await subscribe_and_listen()

        mock_process_message.assert_awaited_once_with(message['params'], mock_reader, mock_writer)
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()

    @patch('asyncio.open_connection')
    @patch('sys.stderr', new_callable=io.StringIO)
    async def test_subscribe_and_listen_json_decode_error(self, mock_stderr, mock_open_connection):
        """Tests that a non-JSON message is handled correctly."""
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        # Simulate one invalid message and then EOF
        mock_reader.at_eof.side_effect = [False, True]
        mock_reader.readline.side_effect = [b'this is not json\n']

        await subscribe_and_listen()

        self.assertIn("ERROR: Received non-JSON message:", mock_stderr.getvalue())

    @patch('asyncio.open_connection')
    @patch('s7_watcher.process_message', side_effect=Exception("Processing error"))
    @patch('sys.stderr', new_callable=io.StringIO)
    async def test_subscribe_and_listen_processing_exception(self, mock_stderr, mock_process_message, mock_open_connection):
        """Tests that an exception during message processing is caught and logged."""
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        # Simulate one valid message that causes a processing error, then EOF
        mock_reader.at_eof.side_effect = [False, True]
        message = {"method": "receive", "params": {}}
        mock_reader.readline.side_effect = [json.dumps(message).encode('utf-8') + b'\n']

        await subscribe_and_listen()

        mock_process_message.assert_awaited_once()
        self.assertIn("ERROR: Could not process message.", mock_stderr.getvalue())

if __name__ == '__main__':
    unittest.main()
