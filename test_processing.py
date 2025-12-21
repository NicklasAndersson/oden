import unittest
from unittest.mock import patch, mock_open, AsyncMock
import os
import asyncio
import json
import config
import importlib
from processing import (
    _extract_message_details,
    process_message
)

class TestProcessing(unittest.IsolatedAsyncioTestCase):

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

        # Patch formatting.VAULT_PATH
        self.patcher_vault_path = patch('formatting.VAULT_PATH', 'mock_vault')
        self.patcher_vault_path.start()

    def tearDown(self):
        self.patcher_get_config.stop()
        self.patcher_vault_path.stop()
        # Reload config module again to clean up the mock
        import config
        import importlib
        importlib.reload(config)

    def test_extract_message_details_data_message(self):
        envelope = {
            "dataMessage": {
                "message": "Hello",
                "groupV2": {"name": "Test Group", "id": "group123"}
            }
        }
        msg, group_title, group_id, attachments = _extract_message_details(envelope)
        self.assertEqual(msg, "Hello")
        self.assertEqual(group_title, "Test Group")
        self.assertEqual(group_id, "group123")
        self.assertEqual(attachments, [])

    def test_extract_message_details_sync_message(self):
        envelope = {
            "syncMessage": {
                "sentMessage": {
                    "message": "Hi there",
                    "groupInfo": {"groupName": "Sync Group", "groupId": "group456"}
                }
            }
        }
        msg, group_title, group_id, attachments = _extract_message_details(envelope)
        self.assertEqual(msg, "Hi there")
        self.assertEqual(group_title, "Sync Group")
        self.assertEqual(group_id, "group456")
        self.assertEqual(attachments, [])

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('config.VAULT_PATH', 'vault')
    async def test_process_message_new_file(self, mock_exists, mock_makedirs, mock_open):
        mock_exists.return_value = False
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000, # GMT: Tuesday 16 December 2025 13:10:00
                "dataMessage": {
                    "message": "Hello world",
                    "groupV2": {"name": "Test Group", "id": "group123"}
                }
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        mock_makedirs.assert_called_once_with(os.path.join("mock_vault", "Test Group"), exist_ok=True)
        mock_open.assert_called_once_with(os.path.join("mock_vault", "Test Group", "161310-123-John_Doe.md"), "a", encoding="utf-8")
        
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        
        self.assertIn("# Test Group", written_content)
        self.assertIn("Avsändare: John Doe ( #tel-123)", written_content)
        self.assertIn("## Meddelande", written_content)
        self.assertIn("Hello world", written_content)

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('config.VAULT_PATH', 'vault')
    async def test_process_message_with_maps_link(self, mock_exists, mock_makedirs, mock_open):
        mock_exists.return_value = False
        message_obj = {
            "envelope": {
                "sourceName": "Jane Doe",
                "sourceNumber": "+456",
                "timestamp": 1765890600000,
                "dataMessage": {
                    "message": "Check this location https://maps.google.com/maps?q=59.514828%2C17.767852",
                    "groupV2": {"name": "Maps Group", "id": "group789"}
                }
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        mock_makedirs.assert_called_once_with(os.path.join("mock_vault", "Maps Group"), exist_ok=True)
        mock_open.assert_called_once_with(os.path.join("mock_vault", "Maps Group", "161310-456-Jane_Doe.md"), "a", encoding="utf-8")
        
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        
        
        self.assertIn("---\nlocations: \"\"\n---\n\n", written_content)
        self.assertIn("[Position](geo:59.514828,17.767852)\n", written_content)
        self.assertIn("Check this location https://maps.google.com/maps?q=59.514828%2C17.767852", written_content)


    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('config.VAULT_PATH', 'vault')
    async def test_process_message_append_file(self, mock_exists, mock_makedirs, mock_open):
        mock_exists.return_value = True
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000, # GMT: Tuesday 16 December 2025 13:10:00
                "dataMessage": {
                    "message": "Another message",
                    "groupV2": {"name": "Test Group", "id": "group123"}
                }
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        mock_makedirs.assert_called_once_with(os.path.join("mock_vault", "Test Group"), exist_ok=True)
        mock_open.assert_called_once_with(os.path.join("mock_vault", "Test Group", "161310-123-John_Doe.md"), "a", encoding="utf-8")
        
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        self.assertIn("\n---\n", written_content)
        self.assertIn("## Meddelande", written_content)
        self.assertIn("Another message", written_content)

    @patch('processing._send_reply')
    @patch('builtins.open', new_callable=mock_open, read_data="HELP_TEXT")
    @patch('os.path.exists', return_value=True)
    async def test_process_message_command_exists(self, mock_exists, mock_open, mock_send_reply):
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#help",
                    "groupV2": {"name": "Test Group", "id": "group123"}
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_exists.assert_called_once_with("responses/help.md")
        mock_open.assert_called_once_with("responses/help.md", "r", encoding="utf-8")
        mock_send_reply.assert_awaited_once_with("group123", "HELP_TEXT", mock_writer)

    @patch('processing._send_reply')
    @patch('builtins.open', new_callable=mock_open, read_data="OK_TEXT")
    @patch('os.path.exists', return_value=True)
    async def test_process_message_command_exists_ok(self, mock_exists, mock_open, mock_send_reply):
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#ok",
                    "groupV2": {"name": "Test Group", "id": "group123"}
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_exists.assert_called_once_with("responses/ok.md")
        mock_open.assert_called_once_with("responses/ok.md", "r", encoding="utf-8")
        mock_send_reply.assert_awaited_once_with("group123", "OK_TEXT", mock_writer)

    @patch('processing._send_reply')
    @patch('os.path.exists', return_value=False)
    async def test_process_message_command_not_exists(self, mock_exists, mock_send_reply):
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#foo",
                    "groupV2": {"name": "Test Group", "id": "group123"}
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_exists.assert_called_once_with("responses/foo.md")
        mock_send_reply.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
