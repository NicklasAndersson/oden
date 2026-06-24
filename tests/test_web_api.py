"""Web GUI API endpoint tests.

Tests use aiohttp's built-in test client (no browser needed).
"""

import json
import tempfile
import unittest.mock
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from oden.web_server import create_app


class TestWebAPIEndpoints(AioHTTPTestCase):
    """Test that all API endpoints respond correctly."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def test_index_returns_html(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.content_type)
        text = await resp.text()
        self.assertIn("<html", text.lower())

    async def test_api_config_returns_json(self):
        resp = await self.client.get("/api/config")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "application/json")

    async def test_api_logs_returns_json(self):
        resp = await self.client.get("/api/logs")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "application/json")
        data = await resp.json()
        self.assertIsInstance(data, list)

    async def test_api_templates_returns_json(self):
        resp = await self.client.get("/api/templates")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "application/json")

    async def test_api_groups_returns_json(self):
        resp = await self.client.get("/api/groups")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "application/json")

    async def test_api_invitations_returns_json(self):
        resp = await self.client.get("/api/invitations")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "application/json")

    async def test_api_contacts_returns_json(self):
        resp = await self.client.get("/api/contacts")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("contacts", data)

    async def test_api_accounts_returns_json(self):
        resp = await self.client.get("/api/accounts")
        self.assertEqual(resp.status, 200)


class TestAccountManagementAPI(AioHTTPTestCase):
    """Regression tests for account listing and deletion."""

    async def get_application(self):
        return create_app(setup_mode=False)

    @unittest.mock.patch("oden.web_handlers.account_handlers.get_app_state")
    @unittest.mock.patch(
        "oden.web_handlers.account_handlers.get_existing_accounts",
        return_value=[{"number": "+46701111111"}],
    )
    async def test_api_accounts_uses_disk_state_over_daemon_cache(
        self,
        mock_get_existing_accounts,
        mock_get_app_state,
    ):
        mock_get_app_state.return_value.writer = object()

        with unittest.mock.patch("oden.web_handlers.account_handlers.cfg.SIGNAL_NUMBER", "+46701111111"):
            resp = await self.client.get("/api/accounts")

        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["accounts"], [{"number": "+46701111111", "active": True}])
        self.assertTrue(data["connected"])

    @unittest.mock.patch("oden.web_handlers.account_handlers.get_app_state")
    @unittest.mock.patch(
        "oden.web_handlers.account_handlers.get_existing_accounts",
        return_value=[],
    )
    async def test_api_accounts_includes_stale_active_account_for_recovery(
        self,
        mock_get_existing_accounts,
        mock_get_app_state,
    ):
        mock_get_app_state.return_value.writer = object()

        with unittest.mock.patch("oden.web_handlers.account_handlers.cfg.SIGNAL_NUMBER", "+46701111111"):
            resp = await self.client.get("/api/accounts")

        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(
            data["accounts"],
            [{"number": "+46701111111", "active": True, "stale": True}],
        )
        self.assertFalse(data["active_valid"])

    async def test_force_delete_removes_account_from_all_known_stores(self):
        number = "+46702222222"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store_one = root / "store-one"
            store_two = root / "store-two"

            for store, rel_path in ((store_one, "acct-a"), (store_two, "acct-b")):
                account_dir = store / "data" / rel_path
                account_dir.mkdir(parents=True)
                accounts_file = store / "data" / "accounts.json"
                accounts_file.write_text(
                    json.dumps(
                        {
                            "accounts": [
                                {"number": number, "path": rel_path},
                            ]
                        }
                    )
                )

            with (
                unittest.mock.patch(
                    "oden.web_handlers.account_handlers.get_signal_data_search_paths",
                    return_value=[store_one, store_two],
                ),
                unittest.mock.patch("oden.web_handlers.account_handlers.cfg.SIGNAL_NUMBER", "+46709999999"),
            ):
                resp = await self.client.delete(f"/api/accounts/{number}/force")

            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data["success"])

            for store in (store_one, store_two):
                accounts_file = store / "data" / "accounts.json"
                contents = json.loads(accounts_file.read_text())
                self.assertEqual(contents["accounts"], [])
            self.assertFalse((store_one / "data" / "acct-a").exists())
            self.assertFalse((store_two / "data" / "acct-b").exists())

    @unittest.mock.patch("oden.web_handlers.account_handlers.get_app_state")
    @unittest.mock.patch("oden.web_handlers._helpers.get_app_state")
    async def test_delete_account_cleans_up_disk_records(
        self,
        mock_require_writer_state,
        mock_handler_state,
    ):
        number = "+46703333333"

        state = unittest.mock.Mock()
        state.writer = object()
        state.send_jsonrpc = unittest.mock.AsyncMock(return_value={"result": {}})
        mock_require_writer_state.return_value = state
        mock_handler_state.return_value = state

        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "store"
            account_dir = store / "data" / "acct-a"
            account_dir.mkdir(parents=True)
            accounts_file = store / "data" / "accounts.json"
            accounts_file.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {"number": number, "path": "acct-a"},
                        ]
                    }
                )
            )

            with (
                unittest.mock.patch(
                    "oden.web_handlers.account_handlers.get_signal_data_search_paths",
                    return_value=[store],
                ),
                unittest.mock.patch("oden.web_handlers.account_handlers.cfg.SIGNAL_NUMBER", "+46709999999"),
            ):
                resp = await self.client.delete(f"/api/accounts/{number}")

            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(json.loads(accounts_file.read_text())["accounts"], [])
            self.assertFalse(account_dir.exists())

    @unittest.mock.patch("oden.web_handlers.account_handlers.get_existing_accounts", return_value=[])
    async def test_force_delete_allows_stale_configured_account(self, mock_get_existing_accounts):
        number = "+46704444444"

        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "store"
            account_dir = store / "data" / "acct-a"
            account_dir.mkdir(parents=True)
            accounts_file = store / "data" / "accounts.json"
            accounts_file.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {"number": number, "path": "acct-a"},
                        ]
                    }
                )
            )

            with (
                unittest.mock.patch(
                    "oden.web_handlers.account_handlers.get_signal_data_search_paths",
                    return_value=[store],
                ),
                unittest.mock.patch("oden.web_handlers.account_handlers.cfg.SIGNAL_NUMBER", number),
            ):
                resp = await self.client.delete(f"/api/accounts/{number}/force")

        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])

    @unittest.mock.patch("oden.web_handlers.account_handlers.get_app_state")
    @unittest.mock.patch("oden.web_handlers._helpers.get_app_state")
    @unittest.mock.patch("oden.web_handlers.account_handlers.get_existing_accounts", return_value=[])
    async def test_delete_account_allows_stale_configured_account(
        self,
        mock_get_existing_accounts,
        mock_require_writer_state,
        mock_handler_state,
    ):
        number = "+46705555555"

        state = unittest.mock.Mock()
        state.writer = object()
        state.send_jsonrpc = unittest.mock.AsyncMock(return_value={"result": {}})
        mock_require_writer_state.return_value = state
        mock_handler_state.return_value = state

        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "store"
            account_dir = store / "data" / "acct-a"
            account_dir.mkdir(parents=True)
            accounts_file = store / "data" / "accounts.json"
            accounts_file.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {"number": number, "path": "acct-a"},
                        ]
                    }
                )
            )

            with (
                unittest.mock.patch(
                    "oden.web_handlers.account_handlers.get_signal_data_search_paths",
                    return_value=[store],
                ),
                unittest.mock.patch("oden.web_handlers.account_handlers.cfg.SIGNAL_NUMBER", number),
            ):
                resp = await self.client.delete(f"/api/accounts/{number}")

            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(json.loads(accounts_file.read_text())["accounts"], [])
            self.assertFalse(account_dir.exists())

    async def test_api_signal_config_returns_json(self):
        resp = await self.client.get("/api/signal-config")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("typingIndicators", data)

    async def test_api_responses_returns_json(self):
        resp = await self.client.get("/api/responses")
        self.assertEqual(resp.status, 200)

    async def test_update_group_rejects_missing_group_id(self):
        resp = await self.client.post(
            "/api/groups/update",
            json={"name": "New Name"},
        )
        self.assertEqual(resp.status, 400)

    async def test_dashboard_js_not_html_escaped(self):
        """Verify that inline JS is not mangled by Jinja2 autoescape.

        The dashboard template uses {% include "js/dashboard.js" %} inside a
        <script> tag. If autoescape ever applies to the included content,
        operators like && would become &amp;&amp; and break the JS.
        """
        resp = await self.client.get("/")
        text = await resp.text()
        # Core functions must be present verbatim
        self.assertIn("function autoSaveConfig()", text)
        self.assertIn("classList.add('show')", text)
        # JS operators must NOT be HTML-escaped
        # (note: &lt; may appear as a literal string in JS, e.g. replace(/</g, '&lt;'),
        # so we only check && which should never appear as &amp;&amp;)
        self.assertNotIn("&amp;&amp;", text)


class TestPipelineManagementAPI(AioHTTPTestCase):
    """Tests for pipeline management API endpoints."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def test_list_pipelines_returns_available_and_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"

            with (
                unittest.mock.patch("oden.web_handlers.pipeline_handlers.cfg.CONFIG_DB", db_path),
                unittest.mock.patch(
                    "oden.web_handlers.pipeline_handlers.cfg.ENABLED_PIPELINES",
                    ["seven_s", "fors", "pedars", "generic_template"],
                ),
            ):
                resp = await self.client.get("/api/pipelines")

            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertIn("available", data)
            self.assertIn("enabled", data)
            self.assertIn("stats", data)
            self.assertTrue(any(p["name"] == "seven_s" for p in data["available"]))
            self.assertTrue(any(p["name"] == "fors" for p in data["available"]))
            self.assertTrue(any(p["name"] == "pedars" for p in data["available"]))
            self.assertTrue(any(p["name"] == "generic_template" for p in data["available"]))

    async def test_toggle_pipeline_disable_updates_enabled_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"

            with (
                unittest.mock.patch("oden.web_handlers.pipeline_handlers.cfg.CONFIG_DB", db_path),
                unittest.mock.patch(
                    "oden.web_handlers.pipeline_handlers.cfg.ENABLED_PIPELINES",
                    ["seven_s", "fors", "pedars", "generic_template"],
                ),
            ):
                resp = await self.client.patch(
                    "/api/pipelines/seven_s/enabled",
                    json={"enabled": False},
                )

            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["updated_list"], ["fors", "pedars", "generic_template"])

    async def test_reorder_pipelines_updates_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"

            with (
                unittest.mock.patch("oden.web_handlers.pipeline_handlers.cfg.CONFIG_DB", db_path),
                unittest.mock.patch(
                    "oden.web_handlers.pipeline_handlers.cfg.ENABLED_PIPELINES",
                    ["seven_s", "fors", "pedars", "generic_template"],
                ),
            ):
                resp = await self.client.post(
                    "/api/pipelines/reorder",
                    json={"order": ["generic_template", "seven_s", "fors", "pedars"]},
                )

            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["updated_list"], ["generic_template", "seven_s", "fors", "pedars"])

    async def test_reorder_pipelines_rejects_unknown_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"

            with (
                unittest.mock.patch("oden.web_handlers.pipeline_handlers.cfg.CONFIG_DB", db_path),
                unittest.mock.patch(
                    "oden.web_handlers.pipeline_handlers.cfg.ENABLED_PIPELINES",
                    ["seven_s", "fors", "pedars", "generic_template"],
                ),
            ):
                resp = await self.client.post(
                    "/api/pipelines/reorder",
                    json={"order": ["not_a_pipeline"]},
                )

            self.assertEqual(resp.status, 400)
            data = await resp.json()
            self.assertIn("Unknown pipeline", data["error"])

    async def test_list_pipelines_includes_group_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"

            with (
                unittest.mock.patch("oden.web_handlers.pipeline_handlers.cfg.CONFIG_DB", db_path),
                unittest.mock.patch(
                    "oden.web_handlers.pipeline_handlers.cfg.ENABLED_PIPELINES",
                    ["group_filter", "seven_s", "fors", "pedars", "generic_template"],
                ),
                unittest.mock.patch(
                    "oden.web_handlers.pipeline_handlers.cfg.PIPELINE_SETTINGS",
                    {"group_filter": {"mode": "whitelist", "groups": ["Alpha"]}},
                ),
            ):
                resp = await self.client.get("/api/pipelines")

            self.assertEqual(resp.status, 200)
            data = await resp.json()
            group_filter = next((p for p in data["available"] if p["name"] == "group_filter"), None)
            self.assertIsNotNone(group_filter)
            self.assertTrue(group_filter["supports_config"])

            enabled_group_filter = next((p for p in data["enabled"] if p["name"] == "group_filter"), None)
            self.assertIsNotNone(enabled_group_filter)
            self.assertEqual(enabled_group_filter["config"]["mode"], "whitelist")
            self.assertEqual(enabled_group_filter["config"]["groups"], ["Alpha"])

    async def test_update_pipeline_config_group_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"

            with (
                unittest.mock.patch("oden.web_handlers.pipeline_handlers.cfg.CONFIG_DB", db_path),
                unittest.mock.patch(
                    "oden.web_handlers.pipeline_handlers.cfg.PIPELINE_SETTINGS",
                    {},
                ),
            ):
                resp = await self.client.patch(
                    "/api/pipelines/group_filter/config",
                    json={"config": {"mode": "blacklist", "groups": ["Alpha", "Bravo"]}},
                )

            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["config"]["mode"], "blacklist")
            self.assertEqual(data["config"]["groups"], ["Alpha", "Bravo"])

    async def test_update_pipeline_config_seven_s_subdir_toggle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"

            with (
                unittest.mock.patch("oden.web_handlers.pipeline_handlers.cfg.CONFIG_DB", db_path),
                unittest.mock.patch(
                    "oden.web_handlers.pipeline_handlers.cfg.PIPELINE_SETTINGS",
                    {},
                ),
            ):
                resp = await self.client.patch(
                    "/api/pipelines/seven_s/config",
                    json={"config": {"vault_subdir_enabled": True, "vault_subdir": "spaningsrapporter"}},
                )

            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data["success"])
            self.assertTrue(data["config"]["vault_subdir_enabled"])
            self.assertEqual(data["config"]["vault_subdir"], "spaningsrapporter")


class TestMessageObservabilityAPI(AioHTTPTestCase):
    """Tests for /api/messages endpoints."""

    async def get_application(self):
        return create_app(setup_mode=False)

    def _create_message(
        self,
        db_path: Path,
        *,
        status: str,
        group_id: str = "g-1",
        group_name: str = "Group 1",
        message_body: str | None = "hello",
    ) -> int:
        from oden.messages_db import create_raw_message, update_message_status

        msg = {
            "envelope": {
                "sourceNumber": "+46701111111",
                "sourceName": "Test Name",
                "timestamp": 1710000000000,
                "dataMessage": {
                    "message": message_body,
                    "groupV2": {
                        "id": group_id,
                        "name": group_name,
                    },
                },
            }
        }
        message_id = create_raw_message(db_path, "+46700000000", msg)
        update_message_status(db_path, message_id, status)
        return message_id

    async def test_messages_list_filters_by_status(self):
        from oden.config_db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            init_db(db_path)
            self._create_message(db_path, status="processed")
            self._create_message(db_path, status="failed")

            with unittest.mock.patch("oden.web_handlers.message_handlers.cfg.CONFIG_DB", db_path):
                resp = await self.client.get("/api/messages?status=processed")

            self.assertEqual(resp.status, 200)
            payload = await resp.json()
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["messages"][0]["status"], "processed")

    async def test_messages_list_can_hide_messages_without_content(self):
        from oden.config_db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            init_db(db_path)
            self._create_message(db_path, status="processed", message_body="hello")
            self._create_message(db_path, status="processed", message_body="   ")
            self._create_message(db_path, status="processed", message_body=None)

            with unittest.mock.patch("oden.web_handlers.message_handlers.cfg.CONFIG_DB", db_path):
                resp = await self.client.get("/api/messages?status=processed&has_content=1")

            self.assertEqual(resp.status, 200)
            payload = await resp.json()
            self.assertEqual(payload["count"], 1)
            self.assertTrue(payload["has_content_only"])
            self.assertEqual(payload["messages"][0]["message_body"], "hello")

    async def test_message_detail_includes_runs_and_events(self):
        from oden.config_db import init_db
        from oden.pipelines_db import append_pipeline_event, complete_pipeline_run, start_pipeline_run

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            init_db(db_path)
            message_id = self._create_message(db_path, status="processed")
            run_id = start_pipeline_run(db_path, message_id, "seven_s")
            append_pipeline_event(db_path, run_id, "pipeline_started", {"pipeline": "seven_s"})
            complete_pipeline_run(db_path, run_id)

            with unittest.mock.patch("oden.web_handlers.message_handlers.cfg.CONFIG_DB", db_path):
                resp = await self.client.get(f"/api/messages/{message_id}")

            self.assertEqual(resp.status, 200)
            payload = await resp.json()
            self.assertEqual(payload["message"]["id"], message_id)
            self.assertEqual(len(payload["runs"]), 1)
            self.assertEqual(payload["runs"][0]["pipeline_name"], "seven_s")
            self.assertEqual(payload["runs"][0]["events"][0]["event_type"], "pipeline_started")

    async def test_message_stats_counts_statuses(self):
        from oden.config_db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            init_db(db_path)
            self._create_message(db_path, status="processed")
            self._create_message(db_path, status="failed")
            self._create_message(db_path, status="ignored")

            with unittest.mock.patch("oden.web_handlers.message_handlers.cfg.CONFIG_DB", db_path):
                resp = await self.client.get("/api/messages/stats")

            self.assertEqual(resp.status, 200)
            payload = await resp.json()
            self.assertEqual(payload["total"], 3)
            self.assertEqual(payload["processed"], 1)
            self.assertEqual(payload["failed"], 1)
            self.assertEqual(payload["ignored"], 1)

    async def test_reprocess_returns_503_without_writer(self):
        with unittest.mock.patch("oden.web_handlers._helpers.get_app_state") as mock_state:
            mock_state.return_value.writer = None
            resp = await self.client.post("/api/messages/123/reprocess")

        self.assertEqual(resp.status, 503)
        payload = await resp.json()
        self.assertFalse(payload["success"])

    async def test_reprocess_calls_orchestrator_when_connected(self):
        state = unittest.mock.Mock()
        state.writer = object()
        state.reader = object()

        with (
            unittest.mock.patch("oden.web_handlers._helpers.get_app_state", return_value=state),
            unittest.mock.patch("oden.web_handlers.message_handlers.get_app_state", return_value=state),
            unittest.mock.patch("oden.web_handlers.message_handlers.PipelineOrchestrator") as mock_orchestrator_class,
        ):
            mock_orchestrator = mock_orchestrator_class.return_value
            mock_orchestrator.reprocess = unittest.mock.AsyncMock(return_value=True)

            resp = await self.client.post("/api/messages/321/reprocess")

        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(payload["success"])
        mock_orchestrator.reprocess.assert_awaited_once()
