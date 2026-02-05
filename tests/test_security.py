"""
Security tests for path traversal and authentication vulnerabilities.
"""

import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import AioHTTPTestCase

from oden.processing import process_message
from oden.web_server import create_app, get_api_token


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


class TestCommandPathTraversal(unittest.IsolatedAsyncioTestCase):
    """Test that command names are validated to prevent path traversal."""

    @patch("oden.processing._send_reply")
    @patch("os.path.exists", return_value=True)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_command_path_traversal_blocked(self, mock_exists, mock_send_reply):
        """Test that path traversal in command name is blocked."""
        # Try to access a file outside the responses directory
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#../../../etc/passwd",  # Malicious command
                    "groupV2": {"name": "Test Group", "id": "group123"},
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        with self.assertLogs("oden.processing", level="WARNING") as log:
            await process_message(message_obj, mock_reader, mock_writer)
            # Should log a warning about blocked command
            self.assertTrue(any("Blocked potentially malicious command" in msg for msg in log.output))

        # Should NOT have tried to read any file
        mock_send_reply.assert_not_awaited()

    @patch("oden.processing._send_reply")
    @patch("os.path.exists", return_value=True)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_command_with_forward_slash_blocked(self, mock_exists, mock_send_reply):
        """Test that forward slashes in command name are blocked."""
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#config/secret",  # Contains forward slash
                    "groupV2": {"name": "Test Group", "id": "group123"},
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        with self.assertLogs("oden.processing", level="WARNING") as log:
            await process_message(message_obj, mock_reader, mock_writer)
            self.assertTrue(any("Blocked potentially malicious command" in msg for msg in log.output))

        mock_send_reply.assert_not_awaited()

    @patch("oden.processing._send_reply")
    @patch("os.path.exists", return_value=True)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_command_with_backslash_blocked(self, mock_exists, mock_send_reply):
        """Test that backslashes in command name are blocked."""
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#config\\secret",  # Contains backslash
                    "groupV2": {"name": "Test Group", "id": "group123"},
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        with self.assertLogs("oden.processing", level="WARNING") as log:
            await process_message(message_obj, mock_reader, mock_writer)
            self.assertTrue(any("Blocked potentially malicious command" in msg for msg in log.output))

        mock_send_reply.assert_not_awaited()

    @patch("oden.processing._send_reply")
    @patch("builtins.open", new_callable=unittest.mock.mock_open, read_data="HELP_TEXT")
    @patch("os.path.exists", return_value=True)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_valid_command_still_works(self, mock_exists, mock_open, mock_send_reply):
        """Test that valid commands without path traversal still work."""
        message_obj = {
            "envelope": {
                "dataMessage": {
                    "message": "#help",  # Valid command
                    "groupV2": {"name": "Test Group", "id": "group123"},
                }
            }
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        # Should have processed the command normally
        mock_exists.assert_called_with("responses/help.md")
        mock_open.assert_called_with("responses/help.md", encoding="utf-8")
        mock_send_reply.assert_awaited_once()


class TestWebAuthentication(AioHTTPTestCase):
    """Test that protected endpoints require authentication."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def test_protected_endpoint_requires_token(self):
        """Test that protected endpoints return 401 without token."""
        resp = await self.client.get("/api/config-file")
        self.assertEqual(resp.status, 401)
        data = await resp.json()
        self.assertFalse(data["success"])
        self.assertIn("Unauthorized", data["error"])

    async def test_protected_endpoint_with_valid_token_query(self):
        """Test that protected endpoints work with valid token in query."""
        token = get_api_token()
        resp = await self.client.get(f"/api/config-file?token={token}")
        # Should not be 401 (might be 404 if config doesn't exist, but not 401)
        self.assertNotEqual(resp.status, 401)

    async def test_protected_endpoint_with_valid_token_header(self):
        """Test that protected endpoints work with valid token in header."""
        token = get_api_token()
        resp = await self.client.get("/api/config-file", headers={"Authorization": f"Bearer {token}"})
        # Should not be 401 (might be 404 if config doesn't exist, but not 401)
        self.assertNotEqual(resp.status, 401)

    async def test_protected_endpoint_with_invalid_token(self):
        """Test that protected endpoints reject invalid token."""
        resp = await self.client.get("/api/config-file?token=invalid_token_here")
        self.assertEqual(resp.status, 401)

    async def test_unprotected_endpoint_no_token_needed(self):
        """Test that unprotected endpoints work without token."""
        resp = await self.client.get("/api/config")
        # Should work without token
        self.assertNotEqual(resp.status, 401)

    async def test_token_endpoint_returns_token(self):
        """Test that /api/token endpoint returns the API token."""
        resp = await self.client.get("/api/token")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("token", data)
        # Should match the token we can get programmatically
        self.assertEqual(data["token"], get_api_token())

    async def test_shutdown_requires_token(self):
        """Test that shutdown endpoint requires token."""
        resp = await self.client.post("/api/shutdown")
        self.assertEqual(resp.status, 401)


if __name__ == "__main__":
    unittest.main()
