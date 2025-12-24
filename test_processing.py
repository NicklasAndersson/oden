import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, mock_open, patch

import config
import importlib

from processing import _extract_message_details, process_message

class TestProcessing(unittest.IsolatedAsyncioTestCase):

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

    @patch('processing.REGEX_PATTERNS', {"reg": r'\bREG\d{3}\b'})
    def test_apply_regex_links(self):
        from processing import _apply_regex_links
        text = "This is a test for REG123 and also REG456. This should not be linked: [[REG789]]."
        expected = "This is a test for [[REG123]] and also [[REG456]]. This should not be linked: [[REG789]]."
        self.assertEqual(_apply_regex_links(text), expected)

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('processing.VAULT_PATH', 'mock_vault')
    async def test_process_message_new_file(self, mock_exists, mock_makedirs, mock_open):
        mock_exists.return_value = False
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000, # A fixed timestamp
                "dataMessage": {
                    "message": "Hello world",
                    "groupV2": {"name": "Test Group", "id": "group123"}
                }
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        mock_makedirs.assert_called_with(os.path.join("mock_vault", "Test Group"), exist_ok=True)
        mock_open.assert_called_with(os.path.join("mock_vault", "Test Group", "161410-123-John_Doe.md"), "a", encoding="utf-8")
        
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        
        self.assertIn("# Test Group", written_content)
        self.assertIn("Avsändare: John Doe ( [[+123]])", written_content)
        self.assertIn("## Meddelande", written_content)
        self.assertIn("Hello world", written_content)
    
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('processing.VAULT_PATH', 'mock_vault')
    async def test_process_message_with_attachment(self, mock_exists, mock_makedirs, mock_open_mock):
        mock_exists.return_value = False
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000,
                "dataMessage": {
                    "message": "Here is an image",
                    "groupV2": {"name": "Attachment Group", "id": "group123"},
                    "attachments": [{
                        "contentType": "image/jpeg",
                        "filename": "test.jpg",
                        "id": "att1",
                        "size": 1234,
                        "data": "aGVsbG8gd29ybGQ=" # "hello world" in base64
                    }]
                }
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        # Check that the attachment subdirectory was created
        attachment_dir = os.path.join("mock_vault", "Attachment Group", "161410_161410-123-John_Doe")
        mock_makedirs.assert_any_call(attachment_dir, exist_ok=True)

        # Check that the markdown file and the attachment file were opened for writing
        md_path = os.path.join("mock_vault", "Attachment Group", "161410-123-John_Doe.md")
        att_path = os.path.join(attachment_dir, "1_test.jpg")
        
        # Check calls to open
        mock_open_mock.assert_any_call(md_path, "a", encoding="utf-8")
        mock_open_mock.assert_any_call(att_path, "wb")

        # Check content of markdown file
        handle = mock_open_mock()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list if call.args[0].strip() != "---\n")
        self.assertIn("## Bilagor", written_content)
        self.assertIn("![[161410_161410-123-John_Doe/1_test.jpg]]", written_content)

        # Check content of attachment file
        handle.write.assert_any_call(b'hello world')

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('processing.VAULT_PATH', 'mock_vault')
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

        mock_makedirs.assert_called_with(os.path.join("mock_vault", "Maps Group"), exist_ok=True)
        mock_open.assert_called_with(os.path.join("mock_vault", "Maps Group", "161410-456-Jane_Doe.md"), "a", encoding="utf-8")
        
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        
        self.assertIn("---\nlocations: \"\"\n---\n\n", written_content)
        self.assertIn("[Position](geo:59.514828,17.767852)\n", written_content)
        self.assertIn("Check this location https://maps.google.com/maps?q=59.514828%2C17.767852", written_content)


    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('processing.VAULT_PATH', 'mock_vault')
    async def test_process_message_append_file(self, mock_exists, mock_makedirs, mock_open):
        mock_exists.return_value = True
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000,
                "dataMessage": {
                    "message": "Another message",
                    "groupV2": {"name": "Test Group", "id": "group123"}
                }
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        mock_makedirs.assert_called_with(os.path.join("mock_vault", "Test Group"), exist_ok=True)
        mock_open.assert_called_with(os.path.join("mock_vault", "Test Group", "161410-123-John_Doe.md"), "a", encoding="utf-8")
        
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

    @patch('builtins.open', new_callable=mock_open)
    async def test_process_message_skip_conditions(self, mock_open):
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        
        # Test skipping non-group message
        non_group_message = {
            "envelope": {
                "sourceName": "John Doe", "timestamp": 123,
                "dataMessage": {"message": "Hello"}
            }
        }
        await process_message(non_group_message, mock_reader, mock_writer)
        mock_open.assert_not_called()

        mock_open.reset_mock()

        # Test skipping message with no content and no attachments
        empty_message = {
            "envelope": {
                "sourceName": "John Doe", "timestamp": 123,
                "dataMessage": {"groupV2": {"name": "Test Group"}}
            }
        }
        await process_message(empty_message, mock_reader, mock_writer)
        mock_open.assert_not_called()



if __name__ == '__main__':
    unittest.main()
