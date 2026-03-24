"""Web GUI config and setup tests — INI import/export, setup wizard, regex patterns.

Tests use aiohttp's built-in test client (no browser needed).
"""

import unittest
import unittest.mock
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from oden.web_server import create_app


class TestConfigImportExport(AioHTTPTestCase):
    """Test /api/config-file and /api/config/export endpoints."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def _get_valid_token(self):
        resp = await self.client.get("/api/token")
        data = await resp.json()
        return data["token"]

    def _auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    # --- export ---

    @unittest.mock.patch(
        "oden.web_handlers.config_handlers.export_config_to_ini",
        return_value="[Vault]\npath = /tmp/vault\n",
    )
    async def test_export_config_ini(self, mock_export):
        """GET /api/config/export returns INI as text/plain download."""
        token = await self._get_valid_token()
        resp = await self.client.get("/api/config/export", headers=self._auth_header(token))
        self.assertEqual(resp.status, 200)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))
        self.assertIn("oden-config.ini", resp.headers["Content-Disposition"])
        body = await resp.text()
        self.assertIn("[Vault]", body)

    # --- import ---

    @unittest.mock.patch("oden.web_handlers.config_handlers.reload_config")
    @unittest.mock.patch(
        "oden.config_db.migrate_from_ini",
        return_value=(True, None),
    )
    async def test_import_config_with_reload(self, mock_migrate, mock_reload):
        """POST /api/config-file with reload=true imports and reloads."""
        ini = "[Vault]\npath = /tmp/vault\n[Signal]\nnumber = +46700000000\n"
        resp = await self.client.post(
            "/api/config-file",
            json={"content": ini, "reload": True},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        mock_reload.assert_called_once()

    @unittest.mock.patch("oden.web_handlers.config_handlers.reload_config")
    @unittest.mock.patch(
        "oden.config_db.migrate_from_ini",
        return_value=(True, None),
    )
    async def test_import_config_without_reload(self, mock_migrate, mock_reload):
        """POST /api/config-file with reload=false imports but does not reload."""
        ini = "[Vault]\npath = /tmp/vault\n[Signal]\nnumber = +46700000000\n"
        resp = await self.client.post(
            "/api/config-file",
            json={"content": ini, "reload": False},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        mock_reload.assert_not_called()

    async def test_import_config_empty_returns_400(self):
        """POST /api/config-file with empty content returns 400."""
        resp = await self.client.post(
            "/api/config-file",
            json={"content": "   ", "reload": False},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])

    async def test_import_config_bad_syntax_returns_400(self):
        """POST /api/config-file with invalid INI syntax returns 400."""
        resp = await self.client.post(
            "/api/config-file",
            json={"content": "NOT VALID INI {{{}}", "reload": False},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("Ogiltig INI-syntax", data["error"])

    async def test_import_config_missing_sections_returns_400(self):
        """POST /api/config-file missing [Vault]/[Signal] returns 400."""
        resp = await self.client.post(
            "/api/config-file",
            json={"content": "[Other]\nkey = val\n", "reload": False},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("[Vault]", data["error"])

    async def test_import_config_invalid_json_returns_400(self):
        """POST /api/config-file with non-JSON body returns 400."""
        resp = await self.client.post(
            "/api/config-file",
            data="this is not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)


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


class TestRegexPatternsConfigSave(AioHTTPTestCase):
    """Test that regex_patterns can be saved via the config-save endpoint."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def _get_valid_token(self) -> str:
        resp = await self.client.get("/api/token")
        data = await resp.json()
        return data["token"]

    def _auth_header(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    async def test_save_valid_regex_patterns(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/config-save",
            json={
                "signal_number": "+46700000000",
                "regex_patterns": {
                    "plate": r"[A-Z]{3}[0-9]{2}[A-Z0-9]",
                    "pnr": r"[0-9]{6}-?[0-9]{4}",
                },
            },
            headers=self._auth_header(token),
        )
        data = await resp.json()
        self.assertTrue(data["success"])

    async def test_save_invalid_regex_pattern_rejected(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/config-save",
            json={
                "signal_number": "+46700000000",
                "regex_patterns": {"bad": "[invalid("},
            },
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])
        self.assertIn("Ogiltigt regex-mönster", data["error"])

    async def test_save_empty_pattern_name_rejected(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/config-save",
            json={
                "signal_number": "+46700000000",
                "regex_patterns": {"": r"[A-Z]+"},
            },
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])
        self.assertIn("namn", data["error"].lower())

    async def test_save_empty_pattern_value_rejected(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/config-save",
            json={
                "signal_number": "+46700000000",
                "regex_patterns": {"test": ""},
            },
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])

    async def test_save_without_regex_preserves_existing(self):
        """When regex_patterns is not in the request, existing patterns are preserved."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/config-save",
            json={"signal_number": "+46700000000"},
            headers=self._auth_header(token),
        )
        data = await resp.json()
        self.assertTrue(data["success"])

    async def test_config_returns_regex_patterns(self):
        """Verify the /api/config endpoint includes regex_patterns."""
        resp = await self.client.get("/api/config")
        data = await resp.json()
        self.assertIn("regex_patterns", data)
        self.assertIsInstance(data["regex_patterns"], dict)

    async def test_save_regex_not_dict_rejected(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/config-save",
            json={
                "signal_number": "+46700000000",
                "regex_patterns": "not-a-dict",
            },
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])

    async def test_save_empty_regex_patterns_accepted(self):
        """Saving an empty dict should be valid (removes all patterns)."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/config-save",
            json={
                "signal_number": "+46700000000",
                "regex_patterns": {},
            },
            headers=self._auth_header(token),
        )
        data = await resp.json()
        self.assertTrue(data["success"])


class TestSetupSaveConfigPreservesExisting(AioHTTPTestCase):
    """Test that setup_save_config_handler preserves existing config values.

    Verifies the fix for the stale CONFIG_DB binding bug where custom
    config values (e.g. append_window_minutes, plus_plus_enabled) were
    lost and replaced with defaults when saving setup config.
    """

    async def get_application(self):
        return create_app(setup_mode=True)

    @unittest.mock.patch("oden.config.set_oden_home_path", return_value=True)
    @unittest.mock.patch("oden.config.validate_oden_home", return_value=(True, None))
    @unittest.mock.patch("oden.config.validate_path_within_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.get_oden_home_path")
    async def test_save_config_preserves_custom_values(
        self, mock_get_home, mock_validate_path, mock_validate_home, mock_set_pointer
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
            custom["plus_plus_enabled"] = True
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
            self.assertTrue(result["plus_plus_enabled"])
            self.assertEqual(result["startup_message"], "none")
            self.assertEqual(result["timezone"], "UTC")

    @unittest.mock.patch("oden.config.set_oden_home_path", return_value=True)
    @unittest.mock.patch("oden.config.validate_oden_home", return_value=(True, None))
    @unittest.mock.patch("oden.config.validate_path_within_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.get_oden_home_path")
    async def test_save_config_updates_setup_managed_keys(
        self, mock_get_home, mock_validate_path, mock_validate_home, mock_set_pointer
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
            old_config["plus_plus_enabled"] = True
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
            self.assertTrue(result["plus_plus_enabled"])


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


class TestMergeIniIntoDB(unittest.TestCase):
    """Test _merge_ini_into_db helper for recovery INI auto-merge."""

    def test_merge_replaces_default_signal_number(self):
        """INI signal_number should replace DB default placeholder."""
        import tempfile

        from oden.config_db import DEFAULT_CONFIG, get_all_config, init_db, save_all_config
        from oden.web_handlers.setup_handlers import _merge_ini_into_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            ini_path = Path(tmpdir) / "config.ini"

            # Create DB with defaults
            init_db(db_path)
            save_all_config(db_path, DEFAULT_CONFIG)

            # Create INI with real values
            ini_path.write_text(
                "[Signal]\nnumber = +46766865402\ndisplay_name = Oden\n"
                "[Vault]\npath = /tmp/my-vault\n"
                "[Settings]\nwhitelist_groups = Test - oden\n",
                encoding="utf-8",
            )

            result = _merge_ini_into_db(db_path, ini_path)
            self.assertTrue(result)

            config = get_all_config(db_path)
            self.assertEqual(config["signal_number"], "+46766865402")
            self.assertEqual(config["display_name"], "Oden")
            self.assertEqual(config["vault_path"], "/tmp/my-vault")
            self.assertEqual(config["whitelist_groups"], ["Test - oden"])

    def test_merge_does_not_overwrite_custom_values(self):
        """INI values should NOT overwrite non-default DB values."""
        import tempfile

        from oden.config_db import DEFAULT_CONFIG, get_all_config, init_db, save_all_config
        from oden.web_handlers.setup_handlers import _merge_ini_into_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            ini_path = Path(tmpdir) / "config.ini"

            # Create DB with custom (non-default) values
            init_db(db_path)
            custom = dict(DEFAULT_CONFIG)
            custom["signal_number"] = "+46701234567"
            custom["display_name"] = "MyDevice"
            custom["vault_path"] = "/custom/vault"
            save_all_config(db_path, custom)

            # INI has different values
            ini_path.write_text(
                "[Signal]\nnumber = +46766865402\ndisplay_name = Oden\n[Vault]\npath = /other/vault\n",
                encoding="utf-8",
            )

            result = _merge_ini_into_db(db_path, ini_path)
            # No merge should happen because DB has non-default values
            self.assertFalse(result)

            config = get_all_config(db_path)
            self.assertEqual(config["signal_number"], "+46701234567")
            self.assertEqual(config["display_name"], "MyDevice")
            self.assertEqual(config["vault_path"], "/custom/vault")

    def test_merge_partial_defaults(self):
        """Only keys with default values should be merged from INI."""
        import tempfile

        from oden.config_db import DEFAULT_CONFIG, get_all_config, init_db, save_all_config
        from oden.web_handlers.setup_handlers import _merge_ini_into_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            ini_path = Path(tmpdir) / "config.ini"

            # DB has custom signal_number but default display_name
            init_db(db_path)
            custom = dict(DEFAULT_CONFIG)
            custom["signal_number"] = "+46701234567"
            # display_name stays at default "oden"
            save_all_config(db_path, custom)

            ini_path.write_text(
                "[Signal]\nnumber = +46766865402\ndisplay_name = Oden\n",
                encoding="utf-8",
            )

            result = _merge_ini_into_db(db_path, ini_path)
            self.assertTrue(result)

            config = get_all_config(db_path)
            # signal_number should NOT be overwritten (was non-default)
            self.assertEqual(config["signal_number"], "+46701234567")
            # display_name SHOULD be updated (was default "oden", INI has "Oden")
            self.assertEqual(config["display_name"], "Oden")

    def test_merge_missing_files(self):
        """Should return False when files don't exist."""
        import tempfile

        from oden.web_handlers.setup_handlers import _merge_ini_into_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            ini_path = Path(tmpdir) / "config.ini"

            # Neither file exists
            self.assertFalse(_merge_ini_into_db(db_path, ini_path))

            # Only DB exists
            db_path.touch()
            self.assertFalse(_merge_ini_into_db(db_path, ini_path))

    def test_merge_empty_ini(self):
        """Should return False when INI has no relevant sections."""
        import tempfile

        from oden.config_db import DEFAULT_CONFIG, init_db, save_all_config
        from oden.web_handlers.setup_handlers import _merge_ini_into_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            ini_path = Path(tmpdir) / "config.ini"

            init_db(db_path)
            save_all_config(db_path, DEFAULT_CONFIG)
            ini_path.write_text("[Other]\nfoo = bar\n", encoding="utf-8")

            self.assertFalse(_merge_ini_into_db(db_path, ini_path))


class TestRecoveryWithIniMerge(AioHTTPTestCase):
    """Test that recovery auto-merges config.ini values during oden-home setup."""

    async def get_application(self):
        return create_app(setup_mode=True)

    @unittest.mock.patch("oden.config.set_oden_home_path", return_value=True)
    @unittest.mock.patch("oden.config.validate_oden_home", return_value=(True, None))
    @unittest.mock.patch("oden.config.validate_path_within_home")
    @unittest.mock.patch("oden.web_handlers.setup_handlers.is_configured")
    async def test_oden_home_auto_merges_ini_on_recovery(
        self, mock_is_configured, mock_validate_path, mock_validate_home, mock_set_pointer
    ):
        """When config.ini exists alongside config.db, INI values fill in defaults."""
        import tempfile

        from oden import config as cfg
        from oden.config_db import DEFAULT_CONFIG, get_all_config, init_db, save_all_config

        with tempfile.TemporaryDirectory() as tmpdir:
            oden_home = Path(tmpdir)
            db_path = oden_home / "config.db"
            ini_path = oden_home / "config.ini"

            # Create DB with defaults (simulates incomplete initial setup)
            init_db(db_path)
            save_all_config(db_path, DEFAULT_CONFIG)

            # Create INI with real values
            ini_path.write_text(
                "[Signal]\nnumber = +46766865402\ndisplay_name = Oden\n"
                "[Vault]\npath = /tmp/my-vault\n"
                "[Settings]\nwhitelist_groups = Test - oden\n",
                encoding="utf-8",
            )

            cfg._update_paths(oden_home)
            mock_validate_path.return_value = (oden_home, None)
            mock_is_configured.return_value = (True, None)

            resp = await self.client.post(
                "/api/setup/oden-home",
                json={"oden_home": str(oden_home)},
            )
            data = await resp.json()
            self.assertTrue(data["success"])

            # saved_config should reflect the merged values
            self.assertEqual(data["saved_config"]["signal_number"], "+46766865402")
            self.assertEqual(data["saved_config"]["display_name"], "Oden")
            self.assertEqual(data["saved_config"]["vault_path"], "/tmp/my-vault")
            self.assertEqual(data["saved_config"]["whitelist_groups"], ["Test - oden"])

            # Verify DB was actually updated
            config = get_all_config(db_path)
            self.assertEqual(config["signal_number"], "+46766865402")
            self.assertEqual(config["whitelist_groups"], ["Test - oden"])
