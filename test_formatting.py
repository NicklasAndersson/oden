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

    @patch('formatting.VAULT_PATH', 'mock_vault')
    def test_get_safe_group_dir_path(self):
        self.assertEqual(get_safe_group_dir_path("My Awesome Group"), os.path.join("mock_vault", "My Awesome Group"))
        self.assertEqual(get_safe_group_dir_path("Group/With/Slashes"), os.path.join("mock_vault", "Group_With_Slashes"))
        self.assertEqual(get_safe_group_dir_path("!@#$%^&*()"), os.path.join("mock_vault", "__________"))

    def test_format_phone_number(self):
        self.assertEqual(_format_phone_number("+1234567890"), " [[+1234567890]]")
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
        self.assertEqual(format_sender_display("John Doe", "+123"), "John Doe ( [[+123]])")
        self.assertEqual(format_sender_display("Jane Doe", None), "Jane Doe")
        self.assertEqual(format_sender_display(None, "+123"), " [[+123]]")
        self.assertEqual(format_sender_display(None, None), "Okänd")

    @patch('formatting.VAULT_PATH', 'mock_vault')
    def test_get_message_filepath(self):
        dt = datetime.datetime(2025, 12, 18, 10, 30)
        # Test with safe group name
        expected_path_safe = os.path.join("mock_vault", "My Group", "181030-123-John_Doe.md")
        self.assertEqual(get_message_filepath("My Group", dt, "John Doe", "+123"), expected_path_safe)
        
        # Test with unsafe group name
        expected_path_unsafe = os.path.join("mock_vault", "My_Group", "181030-123-John_Doe.md")
        self.assertEqual(get_message_filepath("My/Group", dt, "John Doe", "+123"), expected_path_unsafe)


    def test_format_quote(self):
        quote = {
            "authorName": "Jane Doe",
            "authorNumber": "+456",
            "text": "This is a quote."
        }
        formatted = _format_quote(quote)
        self.assertIn("> **Svarar på Jane Doe ( [[+456]]):**", formatted)
        self.assertIn("> This is a quote.", formatted)

    def test_format_quote_edge_cases(self):
        # Test with missing author name
        quote_no_name = {"authorNumber": "+456", "text": "A quote."}
        formatted_no_name = _format_quote(quote_no_name)
        self.assertIn("> **Svarar på  [[+456]]:**", formatted_no_name)
        
        # Test with missing author number
        quote_no_num = {"authorName": "Jane Doe", "text": "A quote."}
        formatted_no_num = _format_quote(quote_no_num)
        self.assertIn("> **Svarar på Jane Doe:**", formatted_no_num)

        # Test with missing text
        quote_no_text = {"authorName": "Jane Doe", "authorNumber": "+456"}
        formatted_no_text = _format_quote(quote_no_text)
        self.assertIn("> ...", formatted_no_text)
        
        # Test with multi-line text
        quote_multiline = {
            "authorName": "Jane Doe",
            "authorNumber": "+456",
            "text": "Line 1\nLine 2"
        }
        formatted_multiline = _format_quote(quote_multiline)
        self.assertIn("> Line 1", formatted_multiline)
        self.assertIn("> Line 2", formatted_multiline)


if __name__ == '__main__':
    unittest.main()
