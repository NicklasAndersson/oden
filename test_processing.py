import asyncio
import json
import os
import io
import datetime
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
    @patch('formatting.VAULT_PATH', 'mock_vault')
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
    @patch('formatting.VAULT_PATH', 'mock_vault')
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
        attachment_dir = os.path.join("mock_vault", "Attachment Group", "20251216141000_161410-123-John_Doe")
        mock_makedirs.assert_any_call(attachment_dir, exist_ok=True)

        # Check that the markdown file and the attachment file were opened for writing
        md_path = os.path.join("mock_vault", "Attachment Group", "161410-123-John_Doe.md")
        att_path = os.path.join(attachment_dir, "1_test.jpg")
        
        # Check calls to open
        mock_open_mock.assert_any_call(md_path, "a", encoding="utf-8")
        mock_open_mock.assert_any_call(att_path, "wb")

        # Check content of markdown file
        handle = mock_open_mock()
        written_content = "".join(
            call.args[0] for call in handle.write.call_args_list if isinstance(call.args[0], str)
        )
        self.assertIn("## Bilagor", written_content)
        self.assertIn("![[20251216141000_161410-123-John_Doe/1_test.jpg]]", written_content)

        # Check content of attachment file
        handle.write.assert_any_call(b'hello world')

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('formatting.VAULT_PATH', 'mock_vault')
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
    @patch('formatting.VAULT_PATH', 'mock_vault')
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

    @patch('processing._find_latest_file_for_sender', return_value='/mock_vault/My Group/recent_file.md')
    @patch('builtins.open', new_callable=mock_open)
    async def test_process_message_append_plus_plus_success(self, mock_open, mock_find_latest):
        """Tests that a '++' message successfully appends to a recent file."""
        message_obj = {
            "envelope": {
                "sourceName": "John Doe", "sourceNumber": "+123", "timestamp": 123,
                "dataMessage": {
                    "message": "++ adding more details",
                    "groupV2": {"name": "My Group"}
                }
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()
        
        await process_message(message_obj, mock_reader, mock_writer)

        mock_find_latest.assert_called_once()
        mock_open.assert_called_once_with('/mock_vault/My Group/recent_file.md', 'a', encoding='utf-8')
        
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertIn("\n---\n", written_content)
        self.assertIn("adding more details", written_content)

    @patch('processing._find_latest_file_for_sender', return_value=None)
    @patch('builtins.open', new_callable=mock_open)
    @patch('sys.stderr', new_callable=io.StringIO)
    async def test_process_message_append_plus_plus_failure(self, mock_stderr, mock_open, mock_find_latest):
        """Tests that a '++' message fails gracefully when no recent file is found."""
        message_obj = {
            "envelope": {
                "sourceName": "John Doe", "sourceNumber": "+123", "timestamp": 123,
                "dataMessage": {
                    "message": "++ this should fail",
                    "groupV2": {"name": "My Group"}
                }
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()
        
        await process_message(message_obj, mock_reader, mock_writer)

        mock_find_latest.assert_called_once()
        mock_open.assert_not_called()
        self.assertIn("APPEND FAILED", mock_stderr.getvalue())

    @patch('processing._find_latest_file_for_sender', return_value='/mock_vault/My Group/recent_file.md')
    @patch('builtins.open', new_callable=mock_open)
    async def test_process_message_append_on_reply_success(self, mock_open, mock_find_latest):
        """Tests that replying to a recent message from self triggers an append."""
        now_ts_ms = int(datetime.datetime.now().timestamp() * 1000)
        five_mins_ago_ts_ms = now_ts_ms - (5 * 60 * 1000)

        message_obj = {
            "envelope": {
                "sourceName": "John Doe", "sourceNumber": "+123", "timestamp": now_ts_ms,
                "dataMessage": {
                    "message": "This is an addition",
                    "groupV2": {"name": "My Group"},
                    "quote": {
                        "id": five_mins_ago_ts_ms,
                        "author": "+123", # Same author
                        "text": "Original message"
                    }
                }
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()
        
        await process_message(message_obj, mock_reader, mock_writer)

        mock_find_latest.assert_called_once()
        mock_open.assert_called_once_with('/mock_vault/My Group/recent_file.md', 'a', encoding='utf-8')
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertIn("This is an addition", written_content)

    @patch('processing._find_latest_file_for_sender')
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.exists', return_value=False)
    @patch('os.makedirs')
    @patch('formatting.VAULT_PATH', 'mock_vault')
    async def test_process_message_append_on_reply_fallback(self, mock_makedirs, mock_exists, mock_open, mock_find_latest):
        """Tests that replying to an old message or other user falls back to new message creation."""
        now_ts_ms = int(datetime.datetime.now().timestamp() * 1000)
        old_ts_ms = now_ts_ms - (40 * 60 * 1000) # 40 minutes ago

        message_obj = {
            "envelope": {
                "sourceName": "John Doe", "sourceNumber": "+123", "timestamp": now_ts_ms,
                "dataMessage": {
                    "message": "This should be a new file",
                    "groupV2": {"name": "My Group"},
                    "quote": {
                        "id": old_ts_ms, # Too old
                        "author": "+123",
                        "text": "Very old message"
                    }
                }
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()
        
        await process_message(message_obj, mock_reader, mock_writer)

        # Assert that append logic was NOT used, and it fell through to normal processing
        mock_find_latest.assert_not_called()
        mock_open.assert_called_once() # Called once for the new file
        self.assertIn("This should be a new file", mock_open().write.call_args.args[0])
        # Check that the quote is still formatted, since it's a normal reply
        self.assertIn("> **Svarar på", mock_open().write.call_args.args[0])

    @patch('processing._find_latest_file_for_sender', return_value='/mock_vault/My Group/recent_file.md')
    @patch('processing._save_attachments', new_callable=AsyncMock, return_value=["![[new_attachment.jpg]]"])
    @patch('builtins.open', new_callable=mock_open)
    async def test_process_message_append_reply_with_attachment_only(self, mock_open, mock_save_attachments, mock_find_latest):
        """Tests the user's bug report: replying with only an attachment should append it."""
        now_ts_ms = int(datetime.datetime.now().timestamp() * 1000)
        one_min_ago_ts_ms = now_ts_ms - (1 * 60 * 1000)

        message_obj = {
            "envelope": {
                "sourceName": "John Doe", "sourceNumber": "+123", "timestamp": now_ts_ms,
                "dataMessage": {
                    "message": None, # NO TEXT MESSAGE
                    "groupV2": {"name": "My Group"},
                    "attachments": [{"id": "att1", "filename": "new.jpg"}],
                    "quote": {
                        "id": one_min_ago_ts_ms,
                        "author": "+123", # Same author
                        "text": "Original message"
                    }
                }
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()
        
        await process_message(message_obj, mock_reader, mock_writer)

        # Assert that the append logic was triggered
        mock_find_latest.assert_called_once()
        mock_save_attachments.assert_awaited_once()

        # Assert that the file was appended to with the new attachment link
        mock_open.assert_called_once_with('/mock_vault/My Group/recent_file.md', 'a', encoding='utf-8')
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertIn("## Bilagor", written_content)
        self.assertIn("![[new_attachment.jpg]]", written_content)


    @patch('builtins.open', new_callable=mock_open)
    @patch('sys.stderr', new_callable=io.StringIO)
    async def test_process_message_ignore_double_dash(self, mock_stderr, mock_open):
        """Tests that a message starting with '--' is ignored."""
        message_obj = {
            "envelope": {
                "sourceName": "John Doe", "sourceNumber": "+123", "timestamp": 123,
                "dataMessage": {
                    "message": "-- This is a comment and should be ignored.",
                    "groupV2": {"name": "My Group"}
                }
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()
        
        await process_message(message_obj, mock_reader, mock_writer)

        mock_open.assert_not_called()
        self.assertIn("Skipping message: Starts with '--'.", mock_stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
