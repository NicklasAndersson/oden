import datetime
import os
import unittest
from unittest.mock import patch

import config
import importlib

from formatting import (
    _format_phone_number,
    _format_quote,
    create_message_filename,
    format_sender_display,
    get_message_filepath,
    get_safe_group_dir_path,
)

class TestFormatting(unittest.TestCase):

    def setUp(self):
        # Mock configuration
        self.patcher_get_config = patch('config.get_config')
        self.mock_get_config = self.patcher_get_config.start()
        self.mock_get_config.return_value = {
            'vault_path': 'mock_vault',
            'inbox_path': 'mock_inbox',
            'signal_number': 'mock_signal_number'
        }
        importlib.reload(config)

        # Patch formatting.VAULT_PATH
        self.patcher_vault_path = patch('formatting.VAULT_PATH', 'mock_vault')
        self.patcher_vault_path.start()

    def tearDown(self):
        self.patcher_get_config.stop()
        self.patcher_vault_path.stop()
        importlib.reload(config)

    def test_get_safe_group_dir_path(self):
        self.assertEqual(get_safe_group_dir_path("My Awesome Group"), os.path.join("mock_vault", "My Awesome Group"))
        self.assertEqual(get_safe_group_dir_path("Group/With/Slashes"), os.path.join("mock_vault", "Group_With_Slashes"))
        self.assertEqual(get_safe_group_dir_path("!@#$%^&*()"), os.path.join("mock_vault", "__________"))

    def test_format_phone_number(self):
        self.assertEqual(_format_phone_number("+1234567890"), " [[1234567890]]")
        self.assertEqual(_format_phone_number("1234567890"), " [[1234567890]]")
        self.assertIsNone(_format_phone_number(None))

    def test_create_message_filename(self):
        dt = datetime.datetime(2025, 12, 18, 10, 30)
        self.assertEqual(create_message_filename(dt, "John Doe", "+123"), "181030-123-John_Doe.md")
        self.assertEqual(create_message_filename(dt, "Jane Doe", None), "181030-Jane_Doe.md")
        self.assertEqual(create_message_filename(dt, None, "+123"), "181030-123.md")
        self.assertEqual(create_message_filename(dt, None, None), "181030-unknown.md")
        self.assertEqual(create_message_filename(dt, "With/Slashes", "+123"), "181030-123-With_Slashes.md")

    def test_format_sender_display(self):
        self.assertEqual(format_sender_display("John Doe", "+123"), "John Doe ( [[123]])")
        self.assertEqual(format_sender_display("Jane Doe", None), "Jane Doe")
        self.assertEqual(format_sender_display(None, "+123"), " [[123]]")
        self.assertEqual(format_sender_display(None, None), "Okänd")

    def test_get_message_filepath(self):
        dt = datetime.datetime(2025, 12, 18, 10, 30)
        expected_path = os.path.join("mock_vault", "My Group", "181030-123-John_Doe.md")
        self.assertEqual(get_message_filepath("My Group", dt, "John Doe", "+123"), expected_path)

    def test_format_quote(self):
        quote = {
            "authorName": "Jane Doe",
            "authorNumber": "+456",
            "text": "This is a quote."
        }
        formatted = _format_quote(quote)
        self.assertIn("> **Svarar på Jane Doe ( [[456]]):**", formatted)
        self.assertIn("> This is a quote.", formatted)

if __name__ == '__main__':
    unittest.main()
