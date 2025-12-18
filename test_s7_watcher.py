
import unittest
from unittest.mock import patch, mock_open
import os
import datetime
import re
from s7_watcher import (
    get_safe_group_dir_path,
    _format_phone_number,
    create_message_filename,
    format_sender_display,
    get_message_filepath,
    _extract_message_details,
    _format_quote,
    process_message
)

class TestS7Watcher(unittest.TestCase):

    def test_get_safe_group_dir_path(self):
        self.assertEqual(get_safe_group_dir_path("My Awesome Group"), os.path.join("vault", "My Awesome Group"))
        self.assertEqual(get_safe_group_dir_path("Group/With/Slashes"), os.path.join("vault", "Group_With_Slashes"))
        self.assertEqual(get_safe_group_dir_path("!@#$%^&*()"), os.path.join("vault", "__________"))

    def test_format_phone_number(self):
        self.assertEqual(_format_phone_number("+1234567890"), " #tel-1234567890")
        self.assertEqual(_format_phone_number("1234567890"), " #tel-1234567890")
        self.assertIsNone(_format_phone_number(None))

    def test_create_message_filename(self):
        dt = datetime.datetime(2025, 12, 18, 10, 30)
        self.assertEqual(create_message_filename(dt, "John Doe", "+123"), "181030-123-John_Doe.md")
        self.assertEqual(create_message_filename(dt, "Jane Doe", None), "181030-Jane_Doe.md")
        self.assertEqual(create_message_filename(dt, None, "+123"), "181030-123.md")
        self.assertEqual(create_message_filename(dt, None, None), "181030-unknown.md")
        self.assertEqual(create_message_filename(dt, "With/Slashes", "+123"), "181030-123-With_Slashes.md")

    def test_format_sender_display(self):
        self.assertEqual(format_sender_display("John Doe", "+123"), "John Doe ( #tel-123)")
        self.assertEqual(format_sender_display("Jane Doe", None), "Jane Doe")
        self.assertEqual(format_sender_display(None, "+123"), " #tel-123")
        self.assertEqual(format_sender_display(None, None), "Okänd")

    def test_get_message_filepath(self):
        dt = datetime.datetime(2025, 12, 18, 10, 30)
        expected_path = os.path.join("vault", "My Group", "181030-123-John_Doe.md")
        self.assertEqual(get_message_filepath("My Group", dt, "John Doe", "+123"), expected_path)

    def test_extract_message_details_data_message(self):
        envelope = {
            "dataMessage": {
                "message": "Hello",
                "groupV2": {"name": "Test Group", "id": "group123"}
            }
        }
        msg, group_title, group_id = _extract_message_details(envelope)
        self.assertEqual(msg, "Hello")
        self.assertEqual(group_title, "Test Group")
        self.assertEqual(group_id, "group123")

    def test_extract_message_details_sync_message(self):
        envelope = {
            "syncMessage": {
                "sentMessage": {
                    "message": "Hi there",
                    "groupInfo": {"groupName": "Sync Group", "groupId": "group456"}
                }
            }
        }
        msg, group_title, group_id = _extract_message_details(envelope)
        self.assertEqual(msg, "Hi there")
        self.assertEqual(group_title, "Sync Group")
        self.assertEqual(group_id, "group456")

    def test_format_quote(self):
        quote = {
            "authorName": "Jane Doe",
            "authorNumber": "+456",
            "text": "This is a quote."
        }
        formatted = _format_quote(quote)
        self.assertIn("> **Svarar på Jane Doe ( #tel-456):**", formatted)
        self.assertIn("> This is a quote.", formatted)

    @patch('os.path.exists')
    @patch('os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    def test_process_message_new_file(self, mock_open, mock_makedirs, mock_exists):
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

        process_message(message_obj)

        mock_makedirs.assert_called_once_with(os.path.join("vault", "Test Group"), exist_ok=True)
        mock_open.assert_called_once_with(os.path.join("vault", "Test Group", "161310-123-John_Doe.md"), "a", encoding="utf-8")
        
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        
        self.assertIn("# Test Group", written_content)
        self.assertIn("Avsändare: John Doe ( #tel-123)", written_content)
        self.assertIn("## Meddelande", written_content)
        self.assertIn("Hello world", written_content)

    @patch('os.path.exists')
    @patch('os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    def test_process_message_append_file(self, mock_open, mock_makedirs, mock_exists):
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

        process_message(message_obj)

        mock_makedirs.assert_called_once_with(os.path.join("vault", "Test Group"), exist_ok=True)
        mock_open.assert_called_once_with(os.path.join("vault", "Test Group", "161310-123-John_Doe.md"), "a", encoding="utf-8")
        
        handle = mock_open()
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)

        self.assertIn("\n---\n", written_content)
        self.assertIn("## Meddelande", written_content)
        self.assertIn("Another message", written_content)

if __name__ == '__main__':
    unittest.main()
