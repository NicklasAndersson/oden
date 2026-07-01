"""Web GUI config and setup tests — setup wizard, config save/load.

Tests use aiohttp's built-in test client (no browser needed).
"""

import unittest
import unittest.mock
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from oden.web_server import create_app


class TestWebSetupMode(AioHTTPTestCase):
    """Test the setup mode routes."""

    async def get_application(self):
        return create_app(setup_mode=True)

    async def test_root_redirects_to_setup(self):
        resp = await self.client.get("/", allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.headers.get("Location"), "/setup")

    async def test_setup_page_returns_html(self):
        resp = await self.client.get("/setup")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.content_type)

    async def test_setup_status_returns_json(self):
        resp = await self.client.get("/api/setup/status")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "application/json")

    async def test_setup_status_includes_recovery_candidate(self):
        """Test that recovery_candidate is present in status response."""
        resp = await self.client.get("/api/setup/status")
        data = await resp.json()
        # recovery_candidate should be a key in the response (may be null)
        self.assertIn("recovery_candidate", data)


class TestSetupRecoveryFlow(AioHTTPTestCase):
    """Test the config recovery flow when pointer file is missing but config.db exists."""

    async def get_application(self):
        return create_app(setup_mode=True)

    @unittest.mock.patch("oden.web_handlers.setup_handlers.validate_oden_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.DEFAULT_ODEN_HOME")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.is_configured")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.get_oden_home_path")
    async def test_recovery_candidate_returned_when_config_exists(
        self, mock_get_home, mock_is_configured, mock_default_home, mock_validate
    ):
        """When pointer is missing but config.db exists, recovery_candidate is returned."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Create a fake config.db
            (tmp_path / "config.db").touch()

            mock_get_home.return_value = None
            mock_is_configured.return_value = (False, "no_pointer")
            mock_default_home.__truediv__ = lambda self, x: tmp_path / x
            mock_default_home.__str__ = lambda self: str(tmp_path)
            mock_default_home.exists = lambda: True
            # Make validate_oden_home return valid
            mock_validate.return_value = (True, None)

            resp = await self.client.get("/api/setup/status")
            data = await resp.json()
            self.assertEqual(data["recovery_candidate"], str(tmp_path))

    @unittest.mock.patch("oden.web_handlers.setup_handlers.validate_oden_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.DEFAULT_ODEN_HOME")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.is_configured")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.get_oden_home_path")
    async def test_no_recovery_candidate_when_no_config_db(
        self, mock_get_home, mock_is_configured, mock_default_home, mock_validate
    ):
        """When pointer is missing and no config.db exists, recovery_candidate is None."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Empty directory — no config.db

            mock_get_home.return_value = None
            mock_is_configured.return_value = (False, "no_pointer")
            mock_default_home.__truediv__ = lambda self, x: tmp_path / x
            mock_default_home.__str__ = lambda self: str(tmp_path)

            resp = await self.client.get("/api/setup/status")
            data = await resp.json()
            self.assertIsNone(data["recovery_candidate"])

    @unittest.mock.patch("oden.web_handlers.setup_handlers.is_configured")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.get_oden_home_path")
    async def test_no_recovery_candidate_when_configured(self, mock_get_home, mock_is_configured):
        """When already configured, recovery_candidate is None."""
        mock_get_home.return_value = Path("/some/path")
        mock_is_configured.return_value = (True, None)

        resp = await self.client.get("/api/setup/status")
        data = await resp.json()
        self.assertIsNone(data["recovery_candidate"])


class TestConfigSave(AioHTTPTestCase):
    """Test misc config values via the config-save/config endpoints."""

    async def get_application(self):
        return create_app(setup_mode=False)

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
        return create_app(setup_mode=False)

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


class TestSetupSaveConfigPreservesExisting(AioHTTPTestCase):
    """Test that setup_save_config_handler preserves existing config values.

    Verifies the fix for the stale CONFIG_DB binding bug where custom
    config values (e.g. append_window_minutes, startup_message) were
    lost and replaced with defaults when saving setup config.
    """

    async def get_application(self):
        return create_app(setup_mode=True)

    @unittest.mock.patch("oden.signal_manager.get_existing_accounts", return_value=[{"number": "+46701234567"}])
    @unittest.mock.patch("oden.config.set_oden_home_path", return_value=True)
    @unittest.mock.patch("oden.config.validate_oden_home", return_value=(True, None))
    @unittest.mock.patch("oden.config.validate_path_within_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.get_oden_home_path")
    async def test_save_config_preserves_custom_values(
        self, mock_get_home, mock_validate_path, mock_validate_home, mock_set_pointer, mock_accounts
    ):
        """Custom config values must survive the setup save-config handler."""
        import tempfile

        from oden import config as cfg
        from oden.config_db import DEFAULT_CONFIG, get_all_config, init_db, save_all_config

        with tempfile.TemporaryDirectory() as tmpdir:
            oden_home = Path(tmpdir)
            db_path = oden_home / "config.db"

            # Create a config.db with NON-DEFAULT values
            init_db(db_path)
            custom = dict(DEFAULT_CONFIG)
            custom["signal_number"] = "+46701234567"
            custom["vault_path"] = str(Path(tmpdir) / "vault")
            custom["display_name"] = "CustomName"
            custom["append_window_minutes"] = 120
            custom["startup_message"] = "none"
            custom["timezone"] = "UTC"
            save_all_config(db_path, custom)

            # Point the config module to our temp dir
            cfg._update_paths(oden_home)
            mock_get_home.return_value = oden_home
            mock_validate_path.return_value = (oden_home, None)

            # Create the vault directory
            vault_dir = Path(tmpdir) / "new-vault"
            vault_dir.mkdir()

            resp = await self.client.post(
                "/api/setup/save-config",
                json={
                    "vault_path": str(vault_dir),
                    "signal_number": "+46701234567",
                    "display_name": "CustomName",
                },
            )
            data = await resp.json()
            self.assertTrue(data["success"], f"save-config failed: {data}")

            # Verify that NON-setup values were preserved from the existing database
            result = get_all_config(db_path)
            self.assertEqual(result["append_window_minutes"], 120)
            self.assertEqual(result["startup_message"], "none")
            self.assertEqual(result["timezone"], "UTC")

    @unittest.mock.patch("oden.signal_manager.get_existing_accounts", return_value=[{"number": "+46709876543"}])
    @unittest.mock.patch("oden.config.set_oden_home_path", return_value=True)
    @unittest.mock.patch("oden.config.validate_oden_home", return_value=(True, None))
    @unittest.mock.patch("oden.config.validate_path_within_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.get_oden_home_path")
    async def test_save_config_updates_setup_managed_keys(
        self, mock_get_home, mock_validate_path, mock_validate_home, mock_set_pointer, mock_accounts
    ):
        """Setup-managed keys (vault_path, signal_number, display_name) should be updated."""
        import tempfile

        from oden import config as cfg
        from oden.config_db import DEFAULT_CONFIG, get_all_config, init_db, save_all_config

        with tempfile.TemporaryDirectory() as tmpdir:
            oden_home = Path(tmpdir)
            db_path = oden_home / "config.db"

            init_db(db_path)
            old_config = dict(DEFAULT_CONFIG)
            old_config["signal_number"] = "+46701234567"
            old_config["vault_path"] = str(Path(tmpdir) / "old-vault")
            old_config["display_name"] = "OldName"
            old_config["append_window_minutes"] = 90
            old_config["startup_message"] = "all"
            save_all_config(db_path, old_config)

            cfg._update_paths(oden_home)
            mock_get_home.return_value = oden_home
            mock_validate_path.return_value = (oden_home, None)

            new_vault = Path(tmpdir) / "new-vault"
            new_vault.mkdir()

            resp = await self.client.post(
                "/api/setup/save-config",
                json={
                    "vault_path": str(new_vault),
                    "signal_number": "+46709876543",
                    "display_name": "NewName",
                },
            )
            data = await resp.json()
            self.assertTrue(data["success"])

            result = get_all_config(db_path)
            # Setup-managed keys should be updated
            self.assertEqual(result["vault_path"], str(new_vault))
            self.assertEqual(result["signal_number"], "+46709876543")
            self.assertEqual(result["display_name"], "NewName")
            # Non-setup keys should be preserved from existing config
            self.assertEqual(result["append_window_minutes"], 90)
            self.assertEqual(result["startup_message"], "all")


class TestSetupSaveConfigRejectsUnknownNumber(AioHTTPTestCase):
    """Test that save-config rejects a signal_number not in signal-cli accounts."""

    async def get_application(self):
        return create_app(setup_mode=True)

    @unittest.mock.patch(
        "oden.signal_manager.get_existing_accounts",
        return_value=[{"number": "+46700000001", "uuid": "aaa"}],
    )
    @unittest.mock.patch("oden.config.set_oden_home_path", return_value=True)
    @unittest.mock.patch("oden.config.validate_oden_home", return_value=(True, None))
    @unittest.mock.patch("oden.config.validate_path_within_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.get_oden_home_path")
    async def test_save_config_unknown_number_rejected(
        self, mock_get_home, mock_validate_path, mock_validate_home, mock_set_pointer, mock_accounts
    ):
        """Submitting a number not among signal-cli accounts returns 400."""
        import tempfile

        from oden import config as cfg
        from oden.config_db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            oden_home = Path(tmpdir)
            init_db(oden_home / "config.db")
            cfg._update_paths(oden_home)
            mock_get_home.return_value = oden_home
            mock_validate_path.return_value = (oden_home, None)

            vault_dir = Path(tmpdir) / "vault"
            vault_dir.mkdir()

            resp = await self.client.post(
                "/api/setup/save-config",
                json={
                    "vault_path": str(vault_dir),
                    "signal_number": "+46799999999",
                    "display_name": "Test",
                },
            )
            self.assertEqual(resp.status, 400)
            data = await resp.json()
            self.assertFalse(data["success"])
            self.assertIn("+46700000001", data["error"])


class TestSetupOdenHomeFullyConfigured(AioHTTPTestCase):
    """Test that oden-home handler returns fully_configured flag."""

    async def get_application(self):
        return create_app(setup_mode=True)

    @unittest.mock.patch("oden.config.set_oden_home_path", return_value=True)
    @unittest.mock.patch("oden.config.validate_oden_home", return_value=(True, None))
    @unittest.mock.patch("oden.config.validate_path_within_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.is_configured")
    async def test_fully_configured_true_when_signal_set(
        self, mock_is_configured, mock_validate_path, mock_validate_home, mock_set_pointer
    ):
        """After recovery with valid signal_number, fully_configured should be True."""
        import tempfile

        from oden import config as cfg
        from oden.config_db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            oden_home = Path(tmpdir)
            init_db(oden_home / "config.db")

            cfg._update_paths(oden_home)
            mock_validate_path.return_value = (oden_home, None)
            mock_is_configured.return_value = (True, None)

            resp = await self.client.post(
                "/api/setup/oden-home",
                json={"oden_home": str(oden_home)},
            )
            data = await resp.json()
            self.assertTrue(data["success"])
            self.assertTrue(data["fully_configured"])

    @unittest.mock.patch("oden.config.set_oden_home_path", return_value=True)
    @unittest.mock.patch("oden.config.validate_oden_home", return_value=(True, None))
    @unittest.mock.patch("oden.config.validate_path_within_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.is_configured")
    async def test_fully_configured_false_when_signal_missing(
        self, mock_is_configured, mock_validate_path, mock_validate_home, mock_set_pointer
    ):
        """After recovery without signal_number, fully_configured should be False."""
        import tempfile

        from oden import config as cfg
        from oden.config_db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            oden_home = Path(tmpdir)
            init_db(oden_home / "config.db")

            cfg._update_paths(oden_home)
            mock_validate_path.return_value = (oden_home, None)
            mock_is_configured.return_value = (False, "no_signal_number")

            resp = await self.client.post(
                "/api/setup/oden-home",
                json={"oden_home": str(oden_home)},
            )
            data = await resp.json()
            self.assertTrue(data["success"])
            self.assertFalse(data["fully_configured"])
