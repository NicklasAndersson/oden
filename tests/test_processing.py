import datetime
import os
import unittest
from unittest.mock import AsyncMock, mock_open, patch

from oden.processing import _extract_message_details, extract_coordinates, process_message


class TestProcessing(unittest.IsolatedAsyncioTestCase):
    def test_extract_message_details_data_message(self):
        envelope = {"dataMessage": {"message": "Hello", "groupV2": {"name": "Test Group", "id": "group123"}}}
        msg, group_title, group_id, attachments = _extract_message_details(envelope)
        self.assertEqual(msg, "Hello")
        self.assertEqual(group_title, "Test Group")
        self.assertEqual(group_id, "group123")
        self.assertEqual(attachments, [])

    def test_extract_message_details_sync_message(self):
        envelope = {
            "syncMessage": {
                "sentMessage": {"message": "Hi there", "groupInfo": {"groupName": "Sync Group", "groupId": "group456"}}
            }
        }
        msg, group_title, group_id, attachments = _extract_message_details(envelope)
        self.assertEqual(msg, "Hi there")
        self.assertEqual(group_title, "Sync Group")
        self.assertEqual(group_id, "group456")
        self.assertEqual(attachments, [])

    @patch("oden.processing.render_report")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("oden.config.VAULT_PATH", "mock_vault")
    async def test_process_message_skips_sync_message(self, mock_exists, mock_makedirs, mock_open_file, mock_render):
        """process_message must skip syncMessages (own outgoing messages echoed by signal-cli)."""
        message_obj = {
            "envelope": {
                "sourceName": "Oden",
                "sourceNumber": "+46700000000",
                "timestamp": 1765890600000,
                "syncMessage": {
                    "sentMessage": {
                        "message": "Mottaget.",
                        "groupInfo": {"groupName": "Test Group", "groupId": "group123"},
                    }
                },
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        # Nothing should have been written — the message was our own outgoing reply
        mock_exists.assert_not_called()
        mock_makedirs.assert_not_called()
        mock_open_file.assert_not_called()
        mock_render.assert_not_called()

    @patch("oden.config.REGEX_PATTERNS", {"reg": r"\bREG\d{3}\b"})
    def test_apply_regex_links(self):
        from oden.link_formatter import apply_regex_links

        text = "This is a test for REG123 and also REG456. This should not be linked: [[REG789]]."
        expected = "This is a test for [[REG123]] and also [[REG456]]. This should not be linked: [[REG789]]."
        self.assertEqual(apply_regex_links(text), expected)

    @patch("oden.processing.render_report")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("oden.config.VAULT_PATH", "mock_vault")
    @patch("oden.config.FILENAME_FORMAT", "classic")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_new_file(self, mock_exists, mock_makedirs, mock_open, mock_render):
        mock_exists.return_value = False
        mock_render.return_value = "---\nfileid: 161410-123-John_Doe\n---\n\n# Test Group\n\nTNR: 161410\n\nAvsändare: John Doe ( [[+123]])\n\nGrupp: [[Test Group]]\n\nGrupp id: group123\n\n## Meddelande\n\nHello world\n"
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000,  # A fixed timestamp
                "dataMessage": {"message": "Hello world", "groupV2": {"name": "Test Group", "id": "group123"}},
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        mock_makedirs.assert_called_with(os.path.join("mock_vault", "Test Group"), exist_ok=True)
        mock_open.assert_called_with(
            os.path.join("mock_vault", "Test Group", "161410-123-John_Doe.md"), "w", encoding="utf-8"
        )

        # Verify render_report was called with correct arguments
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args.kwargs
        self.assertEqual(call_kwargs["fileid"], "161410-123-John_Doe")
        self.assertEqual(call_kwargs["group_title"], "Test Group")
        self.assertEqual(call_kwargs["sender_display"], "John Doe ( [[+123]])")
        self.assertEqual(call_kwargs["message"], "Hello world")

    @patch("oden.processing.render_report")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("oden.config.VAULT_PATH", "mock_vault")
    @patch("oden.config.FILENAME_FORMAT", "classic")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_with_attachment(self, mock_exists, mock_makedirs, mock_open_mock, mock_render):
        """Tests that attachments are properly saved and linked in the message file."""
        mock_exists.return_value = False
        mock_render.return_value = "---\nfileid: 161410-123-John_Doe\n---\n\n# Attachment Group\n\n## Meddelande\n\nHere is an image\n\n## Bilagor\n\n![[20251216141000_161410-123-John_Doe/1_test.jpg]]\n"
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000,
                "dataMessage": {
                    "message": "Here is an image",
                    "groupV2": {"name": "Attachment Group", "id": "group123"},
                    "attachments": [
                        {
                            "contentType": "image/jpeg",
                            "filename": "test.jpg",
                            "id": "att1",
                            "size": 1234,
                            "data": "aGVsbG8gd29ybGQ=",  # "hello world" in base64
                        }
                    ],
                },
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
        mock_open_mock.assert_any_call(md_path, "w", encoding="utf-8")
        mock_open_mock.assert_any_call(att_path, "wb")

        # Verify render_report was called with attachment links
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args.kwargs
        self.assertIn("![[20251216141000_161410-123-John_Doe/1_test.jpg]]", call_kwargs["attachments"])

        # Check content of attachment file
        handle = mock_open_mock()
        handle.write.assert_any_call(b"hello world")

    @patch("oden.processing.render_report")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("oden.config.VAULT_PATH", "mock_vault")
    @patch("oden.config.FILENAME_FORMAT", "classic")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_with_maps_link(self, mock_exists, mock_makedirs, mock_open, mock_render):
        mock_exists.return_value = False
        mock_render.return_value = (
            "---\nfileid: 161410-456-Jane_Doe\n---\n\n# Maps Group\n\n[Position](geo:59.514828,17.767852)\n"
        )
        message_obj = {
            "envelope": {
                "sourceName": "Jane Doe",
                "sourceNumber": "+456",
                "timestamp": 1765890600000,
                "dataMessage": {
                    "message": "Check this location https://maps.google.com/maps?q=59.514828%2C17.767852",
                    "groupV2": {"name": "Maps Group", "id": "group789"},
                },
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        mock_makedirs.assert_called_with(os.path.join("mock_vault", "Maps Group"), exist_ok=True)
        mock_open.assert_called_with(
            os.path.join("mock_vault", "Maps Group", "161410-456-Jane_Doe.md"), "w", encoding="utf-8"
        )

        # Verify render_report was called with lat/lon
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args.kwargs
        self.assertEqual(call_kwargs["fileid"], "161410-456-Jane_Doe")
        self.assertEqual(call_kwargs["lat"], "59.514828")
        self.assertEqual(call_kwargs["lon"], "17.767852")

    @patch("oden.processing.render_report")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("oden.config.VAULT_PATH", "mock_vault")
    @patch("oden.config.FILENAME_FORMAT", "classic")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_duplicate_creates_unique_file(
        self, mock_exists, mock_makedirs, mock_open, mock_render
    ):
        """Tests that a duplicate message creates a new file with suffix."""
        # First file exists, second doesn't (simulating -1 suffix)
        mock_exists.side_effect = [True, False]
        mock_render.return_value = (
            "---\nfileid: 161410-123-John_Doe\n---\n\n# Test Group\n\n## Meddelande\n\nAnother message\n"
        )
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000,
                "dataMessage": {"message": "Another message", "groupV2": {"name": "Test Group", "id": "group123"}},
            }
        }

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        await process_message(message_obj, mock_reader, mock_writer)

        mock_makedirs.assert_called_with(os.path.join("mock_vault", "Test Group"), exist_ok=True)
        # Should create file with -1 suffix since original exists
        mock_open.assert_called_with(
            os.path.join("mock_vault", "Test Group", "161410-123-John_Doe-1.md"), "w", encoding="utf-8"
        )

        # Verify render_report was called with correct arguments
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args.kwargs
        self.assertEqual(call_kwargs["fileid"], "161410-123-John_Doe")
        self.assertEqual(call_kwargs["message"], "Another message")

    @patch("oden.processing._send_reply")
    @patch("oden.processing.get_response_by_keyword", return_value="HELP_TEXT")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_command_exists(self, mock_get_response, mock_send_reply):
        message_obj = {
            "envelope": {"dataMessage": {"message": "#help", "groupV2": {"name": "Test Group", "id": "group123"}}}
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_get_response.assert_called_once()
        mock_send_reply.assert_awaited_once_with("group123", "HELP_TEXT", mock_writer)

    @patch("oden.processing._send_reply")
    @patch("oden.processing.get_response_by_keyword", return_value="OK_TEXT")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_command_exists_ok(self, mock_get_response, mock_send_reply):
        message_obj = {
            "envelope": {"dataMessage": {"message": "#ok", "groupV2": {"name": "Test Group", "id": "group123"}}}
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_get_response.assert_called_once()
        mock_send_reply.assert_awaited_once_with("group123", "OK_TEXT", mock_writer)

    @patch("oden.processing._send_reply")
    @patch("oden.processing.get_response_by_keyword", return_value=None)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_command_not_exists(self, mock_get_response, mock_send_reply):
        message_obj = {
            "envelope": {"dataMessage": {"message": "#foo", "groupV2": {"name": "Test Group", "id": "group123"}}}
        }
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_get_response.assert_called_once()
        mock_send_reply.assert_not_awaited()

    @patch("builtins.open", new_callable=mock_open)
    async def test_process_message_skip_conditions(self, mock_open):
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        # Test skipping non-group message
        non_group_message = {
            "envelope": {"sourceName": "John Doe", "timestamp": 123, "dataMessage": {"message": "Hello"}}
        }
        await process_message(non_group_message, mock_reader, mock_writer)
        mock_open.assert_not_called()

        mock_open.reset_mock()

        # Test skipping message with no content and no attachments
        empty_message = {
            "envelope": {"sourceName": "John Doe", "timestamp": 123, "dataMessage": {"groupV2": {"name": "Test Group"}}}
        }
        await process_message(empty_message, mock_reader, mock_writer)
        mock_open.assert_not_called()

    @patch("oden.processing.render_append")
    @patch("oden.config.PLUS_PLUS_ENABLED", True)
    @patch("oden.processing._find_latest_file_for_sender", return_value="/mock_vault/My Group/recent_file.md")
    @patch("builtins.open", new_callable=mock_open)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_append_plus_plus_success(self, mock_open, mock_find_latest, mock_render):
        """Tests that a '++' message successfully appends to a recent file."""
        mock_render.return_value = (
            "---\n\nTNR: 050000 (2026-02-05T00:00:00)\nAvsändare: John Doe ( [[+123]])\n\nadding more details\n"
        )
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 123,
                "dataMessage": {"message": "++ adding more details", "groupV2": {"name": "My Group"}},
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_find_latest.assert_called_once()
        mock_open.assert_called_once_with("/mock_vault/My Group/recent_file.md", "a", encoding="utf-8")

        # Verify render_append was called with correct message (without ++)
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args.kwargs
        self.assertEqual(call_kwargs["message"], "adding more details")

    @patch("oden.processing.render_report")
    @patch("oden.config.PLUS_PLUS_ENABLED", True)
    @patch("oden.processing._find_latest_file_for_sender", return_value=None)
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    @patch("oden.config.VAULT_PATH", "mock_vault")
    @patch("oden.config.FILENAME_FORMAT", "classic")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_append_plus_plus_failure(
        self, mock_makedirs, mock_open, mock_find_latest, mock_render
    ):
        """Tests that a '++' message falls through to create a new file when no recent file is found."""
        mock_render.return_value = "rendered content"
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000,
                "dataMessage": {"message": "++ this should fail", "groupV2": {"name": "My Group"}},
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()

        with self.assertLogs("oden.processing", level="INFO") as log:
            await process_message(message_obj, mock_reader, mock_writer)

            mock_find_latest.assert_called_once()
            self.assertTrue(any("APPEND FAILED" in message for message in log.output))

            # Verify a new file was created (mode "w") with the ++ stripped from the message
            open_args, open_kwargs = mock_open.call_args
            opened_path = open_args[0]
            opened_mode = open_args[1]
            self.assertTrue(
                opened_path.startswith(os.path.join("mock_vault", "My Group")),
                msg=f"Unexpected path used for new file: {opened_path!r}",
            )
            self.assertEqual(opened_mode, "w")
            self.assertEqual(open_kwargs.get("encoding"), "utf-8")

    @patch("oden.processing.render_report")
    @patch("oden.processing.render_append")
    @patch("oden.config.PLUS_PLUS_ENABLED", True)
    @patch("oden.processing._find_latest_file_for_sender", return_value="/mock_vault/My Group/recent_file.md")
    @patch("os.makedirs")
    @patch("oden.config.VAULT_PATH", "mock_vault")
    @patch("oden.config.FILENAME_FORMAT", "classic")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_append_plus_plus_oserror_falls_through(
        self, mock_makedirs, mock_find_latest, mock_render_append, mock_render_report
    ):
        """Tests that a '++' append falling back on OSError creates a new file."""
        mock_render_append.return_value = "appended content"
        mock_render_report.return_value = "rendered content"
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 1765890600000,
                "dataMessage": {"message": "++ this should fallback", "groupV2": {"name": "My Group"}},
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()

        with patch("builtins.open", new_callable=mock_open) as mocked_open:
            # Make the append open call raise OSError, but allow the new-file open to succeed
            mocked_open.side_effect = [OSError("disk full"), mock_open()()]

            with self.assertLogs("oden.processing", level="INFO") as log:
                await process_message(message_obj, mock_reader, mock_writer)

                self.assertTrue(any("Failed to append" in message for message in log.output))

                # Verify a new file was created after the append failed
                calls = mocked_open.call_args_list
                self.assertEqual(len(calls), 2)
                # First call should be the failed append (mode "a")
                self.assertEqual(calls[0][0][1], "a")
                # Second call should be the new file creation (mode "w")
                self.assertEqual(calls[1][0][1], "w")
                self.assertEqual(calls[1][1].get("encoding"), "utf-8")

    @patch("oden.processing.render_append")
    @patch("oden.processing._find_latest_file_for_sender", return_value="/mock_vault/My Group/recent_file.md")
    @patch("builtins.open", new_callable=mock_open)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_append_on_reply_success(self, mock_open, mock_find_latest, mock_render):
        """Tests that replying to a recent message from self triggers an append."""
        mock_render.return_value = "---\n\nTNR: 050000\nAvsändare: John Doe ( [[+123]])\n\nThis is an addition\n"
        now_ts_ms = int(datetime.datetime.now().timestamp() * 1000)
        five_mins_ago_ts_ms = now_ts_ms - (5 * 60 * 1000)

        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": now_ts_ms,
                "dataMessage": {
                    "message": "This is an addition",
                    "groupV2": {"name": "My Group"},
                    "quote": {
                        "id": five_mins_ago_ts_ms,
                        "author": "+123",  # Same author
                        "text": "Original message",
                    },
                },
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        mock_find_latest.assert_called_once()
        mock_open.assert_called_once_with("/mock_vault/My Group/recent_file.md", "a", encoding="utf-8")

        # Verify render_append was called with correct message
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args.kwargs
        self.assertEqual(call_kwargs["message"], "This is an addition")

    @patch("oden.processing.render_report")
    @patch("oden.processing._find_latest_file_for_sender")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists", return_value=False)
    @patch("os.makedirs")
    @patch("oden.config.VAULT_PATH", "mock_vault")
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_append_on_reply_fallback(
        self, mock_makedirs, mock_exists, mock_open, mock_find_latest, mock_render
    ):
        """Tests that replying to an old message or other user falls back to new message creation."""
        mock_render.return_value = "---\nfileid: test\n---\n\n# My Group\n\nThis should be a new file\n\n> **Svarar på +123:**\n> Very old message\n"
        now_ts_ms = int(datetime.datetime.now().timestamp() * 1000)
        old_ts_ms = now_ts_ms - (40 * 60 * 1000)  # 40 minutes ago

        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": now_ts_ms,
                "dataMessage": {
                    "message": "This should be a new file",
                    "groupV2": {"name": "My Group"},
                    "quote": {
                        "id": old_ts_ms,  # Too old
                        "author": "+123",
                        "text": "Very old message",
                    },
                },
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        # Assert that append logic was NOT used, and it fell through to normal processing
        mock_find_latest.assert_not_called()
        mock_open.assert_called_once()  # Called once for the new file

        # Verify render_report was called with quote
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args.kwargs
        self.assertEqual(call_kwargs["message"], "This should be a new file")
        self.assertIsNotNone(call_kwargs["quote_formatted"])
        self.assertIn("Svarar på", call_kwargs["quote_formatted"])

    @patch("oden.processing.render_append")
    @patch("oden.processing._find_latest_file_for_sender", return_value="/mock_vault/My Group/recent_file.md")
    @patch("oden.processing._save_attachments", new_callable=AsyncMock, return_value=["![[new_attachment.jpg]]"])
    @patch("builtins.open", new_callable=mock_open)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_append_reply_with_attachment_only(
        self, mock_open, mock_save_attachments, mock_find_latest, mock_render
    ):
        """Tests the user's bug report: replying with only an attachment should append it."""
        mock_render.return_value = (
            "---\n\nTNR: 050000\nAvsändare: John Doe ( [[+123]])\n\n## Bilagor\n\n![[new_attachment.jpg]]\n"
        )
        now_ts_ms = int(datetime.datetime.now().timestamp() * 1000)
        one_min_ago_ts_ms = now_ts_ms - (1 * 60 * 1000)

        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": now_ts_ms,
                "dataMessage": {
                    "message": None,  # NO TEXT MESSAGE
                    "groupV2": {"name": "My Group"},
                    "attachments": [{"id": "att1", "filename": "new.jpg"}],
                    "quote": {
                        "id": one_min_ago_ts_ms,
                        "author": "+123",  # Same author
                        "text": "Original message",
                    },
                },
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()

        await process_message(message_obj, mock_reader, mock_writer)

        # Assert that the append logic was triggered
        mock_find_latest.assert_called_once()
        mock_save_attachments.assert_awaited_once()

        # Assert that the file was appended to with the new attachment link
        mock_open.assert_called_once_with("/mock_vault/My Group/recent_file.md", "a", encoding="utf-8")

        # Verify render_append was called with attachments
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args.kwargs
        self.assertIn("![[new_attachment.jpg]]", call_kwargs["attachments"])

    @patch("builtins.open", new_callable=mock_open)
    @patch("oden.config.WHITELIST_GROUPS", [])
    @patch("oden.config.IGNORED_GROUPS", set())
    async def test_process_message_ignore_double_dash(self, mock_open):
        """Tests that a message starting with '--' is ignored."""
        message_obj = {
            "envelope": {
                "sourceName": "John Doe",
                "sourceNumber": "+123",
                "timestamp": 123,
                "dataMessage": {
                    "message": "-- This is a comment and should be ignored.",
                    "groupV2": {"name": "My Group"},
                },
            }
        }
        mock_reader, mock_writer = AsyncMock(), AsyncMock()

        with self.assertLogs("oden.processing", level="DEBUG") as log:
            await process_message(message_obj, mock_reader, mock_writer)

            mock_open.assert_not_called()
            self.assertTrue(any("Skipping message: Starts with '--'." in message for message in log.output))


class TestExtractCoordinates(unittest.TestCase):
    """Tests for the extract_coordinates() helper function."""

    def test_google_maps_percent_2c_uppercase(self):
        msg = "Check this https://maps.google.com/maps?q=59.514828%2C17.767852"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.514828", "17.767852"))

    def test_google_maps_percent_2c_lowercase(self):
        msg = "Location: https://maps.google.com/maps?q=59.514828%2c17.767852"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.514828", "17.767852"))

    def test_google_maps_raw_comma(self):
        msg = "Here: https://maps.google.com/maps?q=59.514828,17.767852"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.514828", "17.767852"))

    def test_google_maps_www_prefix(self):
        msg = "https://www.google.com/maps?q=59.33619252903436%2C18.075111752615083"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.33619252903436", "18.075111752615083"))

    def test_google_maps_with_address_text(self):
        msg = "Bomullsvägen 2, 196 38 Kungsängen\n\nhttps://maps.google.com/maps?q=59.509960%2C17.765860"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.509960", "17.765860"))

    def test_apple_maps_q_param(self):
        msg = "https://maps.apple.com/?q=59.514828,17.767852"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.514828", "17.767852"))

    def test_apple_maps_ll_param(self):
        msg = "Look here https://maps.apple.com/?ll=59.514828,17.767852"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.514828", "17.767852"))

    def test_apple_maps_ll_with_label(self):
        msg = "https://maps.apple.com/?ll=59.514828,17.767852&q=Dropped%20Pin"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.514828", "17.767852"))

    def test_openstreetmap_query_params(self):
        msg = "https://www.openstreetmap.org/?mlat=59.514828&mlon=17.767852#map=15/59.514828/17.767852"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.514828", "17.767852"))

    def test_openstreetmap_hash_only(self):
        msg = "https://www.openstreetmap.org/#map=15/59.514828/17.767852"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.514828", "17.767852"))

    def test_openstreetmap_without_www(self):
        msg = "https://openstreetmap.org/?mlat=59.514828&mlon=17.767852"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("59.514828", "17.767852"))

    def test_negative_coordinates_southern_hemisphere(self):
        msg = "https://maps.google.com/maps?q=-33.868800%2C151.209296"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("-33.868800", "151.209296"))

    def test_negative_coordinates_western_hemisphere(self):
        msg = "https://maps.apple.com/?q=40.712776,-74.005974"
        result = extract_coordinates(msg)
        self.assertEqual(result, ("40.712776", "-74.005974"))

    def test_no_location_url(self):
        msg = "Just a normal message with no maps link"
        result = extract_coordinates(msg)
        self.assertIsNone(result)

    def test_empty_message(self):
        result = extract_coordinates("")
        self.assertIsNone(result)

    def test_non_maps_url(self):
        msg = "Check this out https://www.google.com/search?q=hello"
        result = extract_coordinates(msg)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
