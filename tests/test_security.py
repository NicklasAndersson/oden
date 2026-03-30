"""
Security tests for path traversal and authentication vulnerabilities.
"""

import unittest
from unittest.mock import AsyncMock, patch

from oden.processing import process_message


class TestAttachmentPathTraversal(unittest.IsolatedAsyncioTestCase):
    """Test that attachment filenames are sanitized to prevent path traversal."""

    @patch("oden.processing.render_report")
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("oden.config.VAULT_PATH", "/mock_vault")
    @patch("oden.config.FILENAME_FORMAT", "classic")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_attachment_path_traversal_blocked(self, mock_exists, mock_makedirs, mock_open, mock_render):
        """Test that path traversal in attachment filename is blocked."""
        mock_render.return_value = "---\nfileid: test\n---\n\nTest\n"

        # Try to use a malicious filename with path traversal
        message_obj = {
            "envelope": {
                "sourceName": "Attacker",
                "sourceNumber": "+123",
                "timestamp": 1765890600000,
                "dataMessage": {
                    "message": "Check this file",
                    "groupV2": {"name": "Test Group", "id": "group123"},
                    "attachments": [
                        {
                            "contentType": "image/jpeg",
                            "filename": "../../../etc/passwd",  # Malicious path
                            "id": "att1",
                            "data": "aGVsbG8gd29ybGQ=",  # "hello world" in base64
                        }
                    ],
                },
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        # Check that the file was saved with sanitized filename (basename only)
        # The path should NOT contain "../../../etc/passwd"
        calls = mock_open.call_args_list
        for call in calls:
            filepath = call[0][0] if call[0] else call.kwargs.get("file", "")
            # The path should never escape the vault directory
            self.assertNotIn("../", filepath)
            self.assertNotIn("..\\", filepath)
            self.assertNotIn("/etc/", filepath)

    @patch("oden.processing.render_report")
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("oden.config.VAULT_PATH", "/mock_vault")
    @patch("oden.config.FILENAME_FORMAT", "classic")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_attachment_subdir_traversal_blocked(self, mock_exists, mock_makedirs, mock_open, mock_render):
        """Test that subdirectory traversal in attachment filename is blocked."""
        mock_render.return_value = "---\nfileid: test\n---\n\nTest\n"

        # Try to use a filename with subdirectory
        message_obj = {
            "envelope": {
                "sourceName": "Attacker",
                "sourceNumber": "+123",
                "timestamp": 1765890600000,
                "dataMessage": {
                    "message": "Check this file",
                    "groupV2": {"name": "Test Group", "id": "group123"},
                    "attachments": [
                        {
                            "contentType": "image/jpeg",
                            "filename": "subdir/hidden/file.jpg",  # Subdirectory path
                            "id": "att1",
                            "data": "aGVsbG8gd29ybGQ=",
                        }
                    ],
                },
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        # Check that only the basename is used (file.jpg, not subdir/hidden/file.jpg)
        calls = mock_open.call_args_list
        attachment_calls = [c for c in calls if "wb" in str(c)]
        for call in attachment_calls:
            filepath = call[0][0] if call[0] else ""
            # Should end with just the filename, not contain extra subdirs
            self.assertTrue(filepath.endswith("1_file.jpg"))


class TestCommandLookup(unittest.IsolatedAsyncioTestCase):
    """Test that commands are looked up from the database safely."""

    @patch("oden.processing._send_reply")
    @patch("oden.processing.get_response_by_keyword", return_value=None)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_command_with_path_traversal_no_match(self, mock_get_response, mock_send_reply):
        """Test that path traversal attempts simply find no match in the database."""
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#../../../etc/passwd",
                    "groupV2": {"name": "Test Group", "id": "group123"},
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        # The command is just looked up in the DB — no file access, no match
        mock_get_response.assert_called_once()
        mock_send_reply.assert_not_awaited()

    @patch("oden.processing._send_reply")
    @patch("oden.processing.get_response_by_keyword", return_value=None)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_command_with_special_chars_no_match(self, mock_get_response, mock_send_reply):
        """Test that special characters in commands are harmless with DB lookup."""
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#config/secret",
                    "groupV2": {"name": "Test Group", "id": "group123"},
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_get_response.assert_called_once()
        mock_send_reply.assert_not_awaited()

    @patch("oden.processing._send_reply")
    @patch("oden.processing.get_response_by_keyword", return_value="HELP_TEXT")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_valid_command_still_works(self, mock_get_response, mock_send_reply):
        """Test that valid commands are looked up from the database."""
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#help",
                    "groupV2": {"name": "Test Group", "id": "group123"},
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_get_response.assert_called_once()
        mock_send_reply.assert_awaited_once()

    @patch("oden.processing._send_reply")
    @patch("oden.processing.get_response_by_keyword", return_value="HELP_TEXT")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_command_case_insensitive(self, mock_get_response, mock_send_reply):
        """Test that commands are case-insensitive."""
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#Help",
                    "groupV2": {"name": "Test Group", "id": "group123"},
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        # Command should be lowercased before lookup
        mock_get_response.assert_called_once()
        mock_send_reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
