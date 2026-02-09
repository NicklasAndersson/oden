"""
Web GUI tests — API endpoint tests + Playwright visual tests with screenshots.

API tests use aiohttp's built-in test client (no browser needed).
Playwright tests require: pip install playwright && playwright install chromium
"""

import json
import unittest
import unittest.mock
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from oden.web_server import create_app

# Path to sample data fixture
FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_DATA = FIXTURES_DIR / "gui_sample_data.json"

# Directory for screenshots (gitignored)
SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots"


def load_fixture() -> dict:
    """Load the GUI sample data fixture."""
    with open(SAMPLE_DATA, encoding="utf-8") as f:
        return json.load(f)


# ==============================================================================
# API Endpoint Tests (no browser needed)
# ==============================================================================


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

    async def test_api_token_returns_token(self):
        resp = await self.client.get("/api/token")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("token", data)

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

    async def test_api_config_export_returns_text(self):
        resp = await self.client.get("/api/token")
        token_data = await resp.json()
        resp = await self.client.get(
            "/api/config/export",
            headers={"Authorization": f"Bearer {token_data['token']}"},
        )
        self.assertEqual(resp.status, 200)


class TestProtectedEndpointsRequireAuth(AioHTTPTestCase):
    """Test that all protected endpoints reject requests without a valid token
    and accept requests with a valid token.

    This prevents regressions where auth token headers are accidentally
    removed from the dashboard JavaScript.
    """

    async def get_application(self):
        return create_app(setup_mode=False)

    async def _get_valid_token(self) -> str:
        """Fetch a valid API token from the /api/token endpoint."""
        resp = await self.client.get("/api/token")
        data = await resp.json()
        return data["token"]

    def _auth_header(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # /api/config-save
    # ------------------------------------------------------------------
    async def test_config_save_rejects_without_token(self):
        resp = await self.client.post(
            "/api/config-save",
            json={"signal_number": "+46700000000"},
        )
        self.assertEqual(resp.status, 401)

    async def test_config_save_rejects_wrong_token(self):
        resp = await self.client.post(
            "/api/config-save",
            json={"signal_number": "+46700000000"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        self.assertEqual(resp.status, 401)

    async def test_config_save_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/config-save",
            json={"signal_number": "+46700000000"},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # /api/config/export (requires auth)
    # ------------------------------------------------------------------
    async def test_config_export_rejects_without_token(self):
        resp = await self.client.get("/api/config/export")
        self.assertEqual(resp.status, 401)

    async def test_config_export_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.get("/api/config/export", headers=self._auth_header(token))
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # /api/shutdown
    # ------------------------------------------------------------------
    async def test_shutdown_rejects_without_token(self):
        resp = await self.client.post("/api/shutdown")
        self.assertEqual(resp.status, 401)

    async def test_shutdown_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post("/api/shutdown", headers=self._auth_header(token))
        # Should not be 401 (it will be 200 and trigger shutdown)
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # /api/join-group
    # ------------------------------------------------------------------
    async def test_join_group_rejects_without_token(self):
        resp = await self.client.post("/api/join-group", json={"link": "https://signal.group/#test"})
        self.assertEqual(resp.status, 401)

    async def test_join_group_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/join-group",
            json={"link": "https://signal.group/#test"},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # /api/toggle-ignore-group
    # ------------------------------------------------------------------
    async def test_toggle_ignore_rejects_without_token(self):
        resp = await self.client.post("/api/toggle-ignore-group", json={"groupName": "TestGroup"})
        self.assertEqual(resp.status, 401)

    async def test_toggle_ignore_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/toggle-ignore-group",
            json={"groupName": "TestGroup"},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # /api/toggle-whitelist-group
    # ------------------------------------------------------------------
    async def test_toggle_whitelist_rejects_without_token(self):
        resp = await self.client.post("/api/toggle-whitelist-group", json={"groupName": "TestGroup"})
        self.assertEqual(resp.status, 401)

    async def test_toggle_whitelist_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/toggle-whitelist-group",
            json={"groupName": "TestGroup"},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # /api/invitations/accept and /api/invitations/decline
    # ------------------------------------------------------------------
    async def test_invitation_accept_rejects_without_token(self):
        resp = await self.client.post("/api/invitations/accept", json={"groupId": "abc123"})
        self.assertEqual(resp.status, 401)

    async def test_invitation_accept_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/invitations/accept",
            json={"groupId": "abc123"},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)

    async def test_invitation_decline_rejects_without_token(self):
        resp = await self.client.post("/api/invitations/decline", json={"groupId": "abc123"})
        self.assertEqual(resp.status, 401)

    async def test_invitation_decline_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/invitations/decline",
            json={"groupId": "abc123"},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # /api/templates/* (prefix-protected)
    # ------------------------------------------------------------------
    async def test_template_get_rejects_without_token(self):
        resp = await self.client.get("/api/templates/report.md.j2")
        self.assertEqual(resp.status, 401)

    async def test_template_get_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.get(f"/api/templates/report.md.j2?token={token}")
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # /api/responses/* (prefix-protected)
    # ------------------------------------------------------------------
    async def test_response_create_rejects_without_token(self):
        resp = await self.client.post(
            "/api/responses/new",
            json={"keywords": ["test"], "body": "Test response"},
        )
        self.assertEqual(resp.status, 401)

    async def test_response_create_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            f"/api/responses/new?token={token}",
            json={"keywords": ["test"], "body": "Test response"},
        )
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # Verify query-param token also works
    # ------------------------------------------------------------------
    async def test_config_save_accepts_query_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            f"/api/config-save?token={token}",
            json={"signal_number": "+46700000000"},
        )
        self.assertNotEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # Verify unprotected endpoints still work without token
    # ------------------------------------------------------------------
    async def test_unprotected_config_get_works_without_token(self):
        resp = await self.client.get("/api/config")
        self.assertEqual(resp.status, 200)

    async def test_unprotected_logs_works_without_token(self):
        resp = await self.client.get("/api/logs")
        self.assertEqual(resp.status, 200)

    async def test_unprotected_groups_works_without_token(self):
        resp = await self.client.get("/api/groups")
        self.assertEqual(resp.status, 200)

    async def test_unprotected_invitations_works_without_token(self):
        resp = await self.client.get("/api/invitations")
        self.assertEqual(resp.status, 200)


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


# ==============================================================================
# Playwright Visual Tests (requires playwright + chromium)
# ==============================================================================

# Check if playwright is available
try:
    from playwright.async_api import async_playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright not installed — skipping visual tests")
class TestWebGUIScreenshots(AioHTTPTestCase):
    """Visual tests using Playwright to render the GUI and take screenshots."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def _setup_playwright(self):
        """Start Playwright and launch browser (async)."""
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)

    async def _teardown_playwright(self):
        """Close browser and stop Playwright (async)."""
        await self._browser.close()
        await self._pw.stop()

    def _get_base_url(self) -> str:
        """Get the base URL of the running test server."""
        return str(self.server.make_url(""))

    async def _create_page_with_mocked_data(self):
        """Create a Playwright page that intercepts API calls with fixture data."""
        fixture = load_fixture()
        page = await self._browser.new_page(viewport={"width": 1280, "height": 900})

        async def handle_route(route):
            url = route.request.url
            if "/api/logs" in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(fixture["logs"]),
                )
            elif "/api/config" in url and "/api/config-file" not in url and "/api/config/" not in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(fixture["config"]),
                )
            elif "/api/groups" in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "groups": fixture["groups"]}),
                )
            elif "/api/invitations" in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "invitations": []}),
                )
            else:
                await route.continue_()

        await page.route("**/api/**", handle_route)
        return page

    async def test_dashboard_screenshot(self):
        """Take a screenshot of the main dashboard with sample data."""
        await self._setup_playwright()
        try:
            page = await self._create_page_with_mocked_data()
            await page.goto(self._get_base_url())

            # Wait for the data to load (JS polls on intervals)
            await page.wait_for_timeout(2000)

            path = SCREENSHOTS_DIR / "dashboard.png"
            await page.screenshot(path=str(path), full_page=True)
            self.assertTrue(path.exists(), "Dashboard screenshot was not created")
            self.assertGreater(path.stat().st_size, 0, "Dashboard screenshot is empty")
            await page.close()
        finally:
            await self._teardown_playwright()

    async def test_setup_page_screenshot(self):
        """Take a screenshot of the setup wizard page."""
        await self._setup_playwright()
        try:
            page = await self._browser.new_page(viewport={"width": 1280, "height": 900})
            await page.goto(self._get_base_url() + "/setup")

            await page.wait_for_timeout(1000)

            path = SCREENSHOTS_DIR / "setup.png"
            await page.screenshot(path=str(path), full_page=True)
            self.assertTrue(path.exists(), "Setup screenshot was not created")
            self.assertGreater(path.stat().st_size, 0, "Setup screenshot is empty")
            await page.close()
        finally:
            await self._teardown_playwright()

    async def test_dashboard_contains_expected_elements(self):
        """Verify the dashboard renders key UI elements."""
        await self._setup_playwright()
        try:
            page = await self._create_page_with_mocked_data()
            await page.goto(self._get_base_url())
            await page.wait_for_timeout(2000)

            # Check that the page title or heading contains "Oden"
            content = await page.content()
            self.assertIn("Oden", content)
            await page.close()
        finally:
            await self._teardown_playwright()


if __name__ == "__main__":
    unittest.main()
