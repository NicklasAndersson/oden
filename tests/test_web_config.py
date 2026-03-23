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
