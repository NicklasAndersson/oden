"""Web GUI config tests — config save/load, signal-cli controls, running without Signal.

Tests use aiohttp's built-in test client (no browser needed).
"""

import unittest
import unittest.mock

from aiohttp.test_utils import AioHTTPTestCase

from oden.web_server import create_app


class TestConfigSave(AioHTTPTestCase):
    """Test misc config values via the config-save/config endpoints."""

    async def get_application(self):
        return create_app()

    async def test_config_returns_retention_days(self):
        """Verify /api/config includes retention setting for DB-first cleanup."""
        resp = await self.client.get("/api/config")
        data = await resp.json()
        self.assertIn("raw_message_retention_days", data)
        self.assertIsInstance(data["raw_message_retention_days"], int)

    async def test_config_returns_diagnostic_mode(self):
        """Verify /api/config includes diagnostic mode toggle."""
        resp = await self.client.get("/api/config")
        data = await resp.json()
        self.assertIn("diagnostic_mode", data)
        self.assertIsInstance(data["diagnostic_mode"], bool)

    async def test_config_returns_group_split_enabled(self):
        """Verify /api/config includes group split toggle."""
        resp = await self.client.get("/api/config")
        data = await resp.json()
        self.assertIn("group_split_enabled", data)
        self.assertIsInstance(data["group_split_enabled"], bool)

    async def test_save_invalid_retention_days_rejected(self):
        """Retention must be an int between 1 and 3650."""
        resp = await self.client.post(
            "/api/config-save",
            json={
                "signal_number": "+46700000000",
                "raw_message_retention_days": 0,
            },
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])
        self.assertIn("raw_message_retention_days", data["error"])

    async def test_save_diagnostic_mode(self):
        """Verify diagnostic mode can be persisted via /api/config-save."""
        save_resp = await self.client.post(
            "/api/config-save",
            json={
                "signal_number": "+46700000000",
                "diagnostic_mode": True,
            },
        )
        save_data = await save_resp.json()
        self.assertTrue(save_data["success"])

        cfg_resp = await self.client.get("/api/config")
        cfg_data = await cfg_resp.json()
        self.assertTrue(cfg_data["diagnostic_mode"])

    async def test_save_group_split_enabled(self):
        """Verify group_split_enabled can be persisted via /api/config-save."""
        save_resp = await self.client.post(
            "/api/config-save",
            json={
                "signal_number": "+46700000000",
                "group_split_enabled": False,
            },
        )
        save_data = await save_resp.json()
        self.assertTrue(save_data["success"])

        cfg_resp = await self.client.get("/api/config")
        cfg_data = await cfg_resp.json()
        self.assertFalse(cfg_data["group_split_enabled"])


class TestSignalCliControls(AioHTTPTestCase):
    """Test web endpoints for signal-cli lifecycle controls."""

    async def get_application(self):
        return create_app()

    @unittest.mock.patch("oden.app_state.get_app_state")
    async def test_restart_signal_cli_managed(self, mock_get_app_state):
        mock_state = unittest.mock.Mock()
        mock_state.signal_manager = object()
        mock_get_app_state.return_value = mock_state

        resp = await self.client.post("/api/signal-cli/restart")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        mock_state.request_stop.assert_called_once()

    @unittest.mock.patch("oden.app_state.get_app_state")
    async def test_restart_signal_cli_unmanaged_rejected(self, mock_get_app_state):
        mock_state = unittest.mock.Mock()
        mock_state.signal_manager = None
        mock_get_app_state.return_value = mock_state

        resp = await self.client.post("/api/signal-cli/restart")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])

    @unittest.mock.patch("oden.web_server.get_signal_log_status")
    @unittest.mock.patch("oden.web_server.get_signal_cli_version")
    @unittest.mock.patch("oden.web_server.find_signal_cli_executable")
    async def test_signal_cli_status_ok(self, mock_find_executable, mock_get_version, mock_get_log_status):
        mock_find_executable.return_value = "/opt/signal-cli/bin/signal-cli"
        mock_get_version.return_value = "0.14.5"
        mock_get_log_status.return_value = {
            "enabled": False,
            "severity": "info",
            "message": "signal-cli loggning är avstängd. Övervakning körs inte.",
        }

        resp = await self.client.get("/api/signal-cli/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["version_status"], "ok")
        self.assertEqual(data["detected_version"], "0.14.5")
        self.assertEqual(data["log_monitor"]["severity"], "info")

    @unittest.mock.patch("oden.web_server.get_signal_log_status")
    @unittest.mock.patch("oden.web_server.get_signal_cli_version")
    @unittest.mock.patch("oden.web_server.find_signal_cli_executable")
    async def test_signal_cli_status_mismatch(self, mock_find_executable, mock_get_version, mock_get_log_status):
        mock_find_executable.return_value = "/opt/signal-cli/bin/signal-cli"
        mock_get_version.return_value = "0.14.4.1"
        mock_get_log_status.return_value = {
            "enabled": True,
            "severity": "warning",
            "message": "signal-cli visar NullPointerException i loggen.",
        }

        resp = await self.client.get("/api/signal-cli/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["version_status"], "mismatch")
        self.assertEqual(data["detected_version"], "0.14.4.1")
        self.assertEqual(data["log_monitor"]["severity"], "warning")


class TestDashboardWithoutSignal(AioHTTPTestCase):
    """With Signal disabled, the dashboard and its Signal tabs load without errors."""

    async def get_application(self):
        return create_app()

    async def asyncSetUp(self):
        self._patch = unittest.mock.patch("oden.config.SIGNAL_ENABLED", False)
        self._patch.start()
        await super().asyncSetUp()

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self._patch.stop()

    async def test_index_renders_signal_off_state(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("const SIGNAL_ENABLED = false;", text)
        self.assertIn("Oden körs utan Signal", text)
        self.assertIn('<fieldset class="signal-only" disabled>', text)
        self.assertIn('id="signal-connect"', text)
        self.assertIn("Registrera nytt nummer", text)
        self.assertNotIn("/setup", text)

    async def test_polled_endpoints_respond_ok(self):
        for path in ("/api/groups", "/api/invitations", "/api/contacts", "/api/accounts", "/api/signal-config"):
            resp = await self.client.get(path)
            self.assertEqual(resp.status, 200, path)

    async def test_signal_actions_explain_signal_is_off(self):
        resp = await self.client.post("/api/contacts/refresh")
        self.assertEqual(resp.status, 503)
        self.assertEqual((await resp.json())["error"], "Signal är avstängt")
