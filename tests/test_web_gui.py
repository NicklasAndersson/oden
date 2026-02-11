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

    async def test_dashboard_js_not_html_escaped(self):
        """Verify that inline JS is not mangled by Jinja2 autoescape.

        The dashboard template uses {% include "js/dashboard.js" %} inside a
        <script> tag. If autoescape ever applies to the included content,
        operators like && would become &amp;&amp; and break the JS.
        """
        resp = await self.client.get("/")
        text = await resp.text()
        # Core dirty-tracking functions must be present verbatim
        self.assertIn("function updateDirtyState()", text)
        self.assertIn("function snapshotConfig()", text)
        self.assertIn("classList.toggle('show'", text)
        # JS operators must NOT be HTML-escaped
        # (note: &lt; may appear as a literal string in JS, e.g. replace(/</g, '&lt;'),
        # so we only check && which should never appear as &amp;&amp;)
        self.assertNotIn("&amp;&amp;", text)

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


class TestToggleGroupPersistence(AioHTTPTestCase):
    """Test that toggling whitelist/ignore groups persists to config_db."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def _get_valid_token(self) -> str:
        resp = await self.client.get("/api/token")
        data = await resp.json()
        return data["token"]

    def _auth_header(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    @unittest.mock.patch("oden.web_handlers.group_handlers.reload_config")
    @unittest.mock.patch("oden.web_handlers.group_handlers.set_config_value")
    @unittest.mock.patch("oden.web_handlers.group_handlers.get_config_value")
    async def test_toggle_whitelist_adds_group(self, mock_get, mock_set, mock_reload):
        """Toggling whitelist for a new group adds it to config_db."""
        mock_get.return_value = []

        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/toggle-whitelist-group",
            json={"groupName": "TestGroup"},
            headers=self._auth_header(token),
        )
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertIn("TestGroup", data["whitelistGroups"])

        # Verify set_config_value was called with the updated list
        mock_set.assert_called_once()
        call_args = mock_set.call_args
        self.assertEqual(call_args[0][1], "whitelist_groups")
        self.assertIn("TestGroup", call_args[0][2])
        mock_reload.assert_called_once()

    @unittest.mock.patch("oden.web_handlers.group_handlers.reload_config")
    @unittest.mock.patch("oden.web_handlers.group_handlers.set_config_value")
    @unittest.mock.patch("oden.web_handlers.group_handlers.get_config_value")
    async def test_toggle_whitelist_removes_group(self, mock_get, mock_set, mock_reload):
        """Toggling whitelist for an existing group removes it from config_db."""
        mock_get.return_value = ["TestGroup", "OtherGroup"]

        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/toggle-whitelist-group",
            json={"groupName": "TestGroup"},
            headers=self._auth_header(token),
        )
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertNotIn("TestGroup", data["whitelistGroups"])
        self.assertIn("OtherGroup", data["whitelistGroups"])

        call_args = mock_set.call_args
        saved_list = call_args[0][2]
        self.assertNotIn("TestGroup", saved_list)
        self.assertIn("OtherGroup", saved_list)

    @unittest.mock.patch("oden.web_handlers.group_handlers.reload_config")
    @unittest.mock.patch("oden.web_handlers.group_handlers.set_config_value")
    @unittest.mock.patch("oden.web_handlers.group_handlers.get_config_value")
    async def test_toggle_ignore_adds_group(self, mock_get, mock_set, mock_reload):
        """Toggling ignore for a new group adds it to config_db."""
        mock_get.return_value = []

        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/toggle-ignore-group",
            json={"groupName": "IgnoredGroup"},
            headers=self._auth_header(token),
        )
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertIn("IgnoredGroup", data["ignoredGroups"])

        call_args = mock_set.call_args
        self.assertEqual(call_args[0][1], "ignored_groups")
        self.assertIn("IgnoredGroup", call_args[0][2])
        mock_reload.assert_called_once()

    @unittest.mock.patch("oden.web_handlers.group_handlers.reload_config")
    @unittest.mock.patch("oden.web_handlers.group_handlers.set_config_value")
    @unittest.mock.patch("oden.web_handlers.group_handlers.get_config_value")
    async def test_toggle_ignore_removes_group(self, mock_get, mock_set, mock_reload):
        """Toggling ignore for an existing group removes it from config_db."""
        mock_get.return_value = ["IgnoredGroup"]

        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/toggle-ignore-group",
            json={"groupName": "IgnoredGroup"},
            headers=self._auth_header(token),
        )
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertNotIn("IgnoredGroup", data["ignoredGroups"])

        call_args = mock_set.call_args
        saved_list = call_args[0][2]
        self.assertNotIn("IgnoredGroup", saved_list)

    async def test_toggle_whitelist_empty_name_rejected(self):
        """Toggling whitelist with empty group name returns 400."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/toggle-whitelist-group",
            json={"groupName": ""},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)

    async def test_toggle_ignore_empty_name_rejected(self):
        """Toggling ignore with empty group name returns 400."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/toggle-ignore-group",
            json={"groupName": ""},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)


class TestResponsesCRUDEndpoints(AioHTTPTestCase):
    """Test the full CRUD lifecycle for /api/responses endpoints."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def _get_valid_token(self) -> str:
        resp = await self.client.get("/api/token")
        data = await resp.json()
        return data["token"]

    def _auth_header(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # GET /api/responses — list (unprotected)
    # ------------------------------------------------------------------
    async def test_responses_list_returns_json(self):
        """GET /api/responses returns a JSON list."""
        resp = await self.client.get("/api/responses")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "application/json")
        data = await resp.json()
        self.assertIsInstance(data, list)

    # ------------------------------------------------------------------
    # POST /api/responses/new — create (protected)
    # ------------------------------------------------------------------
    @unittest.mock.patch("oden.web_handlers.response_handlers.create_response", return_value=42)
    async def test_create_response_success(self, mock_create):
        """POST /api/responses/new with valid data creates a response."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/responses/new",
            json={"keywords": ["info", "help"], "body": "Här är info."},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["id"], 42)
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        self.assertEqual(call_args[0][1], ["info", "help"])
        self.assertEqual(call_args[0][2], "Här är info.")

    async def test_create_response_missing_keywords(self):
        """POST /api/responses/new without keywords returns 400."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/responses/new",
            json={"body": "Svarstext"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])

    async def test_create_response_missing_body(self):
        """POST /api/responses/new without body returns 400."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/responses/new",
            json={"keywords": ["test"]},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])

    async def test_create_response_invalid_json(self):
        """POST /api/responses/new with non-JSON body returns 400."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/responses/new",
            data=b"not json",
            headers={**self._auth_header(token), "Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["success"])

    @unittest.mock.patch("oden.web_handlers.response_handlers.create_response", return_value=None)
    async def test_create_response_db_failure(self, mock_create):
        """POST /api/responses/new returns 500 when DB create fails."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/responses/new",
            json={"keywords": ["test"], "body": "Test"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 500)
        data = await resp.json()
        self.assertFalse(data["success"])

    # ------------------------------------------------------------------
    # GET /api/responses/{id} — get single (protected via prefix)
    # ------------------------------------------------------------------
    @unittest.mock.patch(
        "oden.web_handlers.response_handlers.get_response_by_id",
        return_value={"id": 1, "keywords": ["läge"], "body": "Allt lugnt."},
    )
    async def test_get_response_by_id_success(self, mock_get):
        """GET /api/responses/1 returns the response."""
        token = await self._get_valid_token()
        resp = await self.client.get(f"/api/responses/1?token={token}")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["id"], 1)
        self.assertEqual(data["keywords"], ["läge"])
        mock_get.assert_called_once()

    @unittest.mock.patch("oden.web_handlers.response_handlers.get_response_by_id", return_value=None)
    async def test_get_response_by_id_not_found(self, mock_get):
        """GET /api/responses/999 returns 404 when not found."""
        token = await self._get_valid_token()
        resp = await self.client.get(f"/api/responses/999?token={token}")
        self.assertEqual(resp.status, 404)
        data = await resp.json()
        self.assertFalse(data["success"])

    async def test_get_response_by_id_requires_auth(self):
        """GET /api/responses/1 without token returns 401."""
        resp = await self.client.get("/api/responses/1")
        self.assertEqual(resp.status, 401)

    # ------------------------------------------------------------------
    # POST /api/responses/{id} — update (protected via prefix)
    # ------------------------------------------------------------------
    @unittest.mock.patch("oden.web_handlers.response_handlers.save_response", return_value=True)
    async def test_update_response_success(self, mock_save):
        """POST /api/responses/1 with valid data updates the response."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/responses/1",
            json={"keywords": ["uppdaterad"], "body": "Ny text"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        self.assertEqual(call_args[0][1], 1)  # response_id
        self.assertEqual(call_args[0][2], ["uppdaterad"])
        self.assertEqual(call_args[0][3], "Ny text")

    @unittest.mock.patch("oden.web_handlers.response_handlers.save_response", return_value=False)
    async def test_update_response_db_failure(self, mock_save):
        """POST /api/responses/1 returns 500 when DB save fails."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/responses/1",
            json={"keywords": ["test"], "body": "Test"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 500)
        data = await resp.json()
        self.assertFalse(data["success"])

    async def test_update_response_missing_keywords(self):
        """POST /api/responses/1 without keywords returns 400."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/responses/1",
            json={"body": "Text utan nyckelord"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)

    async def test_update_response_missing_body(self):
        """POST /api/responses/1 without body returns 400."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/responses/1",
            json={"keywords": ["test"]},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)

    # ------------------------------------------------------------------
    # DELETE /api/responses/{id} — delete (protected via prefix)
    # ------------------------------------------------------------------
    @unittest.mock.patch("oden.web_handlers.response_handlers.delete_response", return_value=True)
    async def test_delete_response_success(self, mock_delete):
        """DELETE /api/responses/1 deletes the response."""
        token = await self._get_valid_token()
        resp = await self.client.delete(
            "/api/responses/1",
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        mock_delete.assert_called_once()

    @unittest.mock.patch("oden.web_handlers.response_handlers.delete_response", return_value=False)
    async def test_delete_response_not_found(self, mock_delete):
        """DELETE /api/responses/999 returns 404 when not found."""
        token = await self._get_valid_token()
        resp = await self.client.delete(
            "/api/responses/999",
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 404)
        data = await resp.json()
        self.assertFalse(data["success"])

    async def test_delete_response_requires_auth(self):
        """DELETE /api/responses/1 without token returns 401."""
        resp = await self.client.delete("/api/responses/1")
        self.assertEqual(resp.status, 401)


# ---------------------------------------------------------------------------
# Template endpoint tests
# ---------------------------------------------------------------------------


class TestTemplateEndpoints(AioHTTPTestCase):
    """Test /api/templates endpoints (list, get, save, preview, reset, export)."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def _get_valid_token(self):
        resp = await self.client.get("/api/token")
        data = await resp.json()
        return data["token"]

    def _auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    # --- list ---

    async def test_list_templates(self):
        """GET /api/templates returns list of available templates."""
        resp = await self.client.get("/api/templates")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("templates", data)
        self.assertTrue(len(data["templates"]) >= 2)
        names = [t["name"] for t in data["templates"]]
        self.assertIn("report.md.j2", names)
        self.assertIn("append.md.j2", names)

    # --- get ---

    @unittest.mock.patch("oden.web_handlers.template_handlers.get_template_content", return_value="# Hello")
    async def test_get_template_success(self, mock_get):
        """GET /api/templates/report.md.j2 returns template content."""
        token = await self._get_valid_token()
        resp = await self.client.get("/api/templates/report.md.j2", headers=self._auth_header(token))
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["content"], "# Hello")
        self.assertEqual(data["key"], "report")
        mock_get.assert_called_once_with("report.md.j2")

    async def test_get_template_unknown_returns_404(self):
        """GET /api/templates/nope.j2 returns 404."""
        token = await self._get_valid_token()
        resp = await self.client.get("/api/templates/nope.j2", headers=self._auth_header(token))
        self.assertEqual(resp.status, 404)

    # --- save ---

    @unittest.mock.patch("oden.web_handlers.template_handlers.validate_template", return_value=(True, None))
    @unittest.mock.patch("oden.web_handlers.template_handlers.save_template_content", return_value=True)
    async def test_save_template_success(self, mock_save, mock_val):
        """POST /api/templates/report.md.j2 saves content."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/report.md.j2",
            json={"content": "# New"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertNotIn("warning", data)

    @unittest.mock.patch(
        "oden.web_handlers.template_handlers.validate_template",
        return_value=(False, "unexpected '}'"),
    )
    @unittest.mock.patch("oden.web_handlers.template_handlers.save_template_content", return_value=True)
    async def test_save_template_with_syntax_warning(self, mock_save, mock_val):
        """POST with bad syntax still saves but returns warning."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/report.md.j2",
            json={"content": "{{ bad }"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertIn("warning", data)

    async def test_save_template_empty_returns_400(self):
        """POST with empty content returns 400."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/report.md.j2",
            json={"content": "   "},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)

    async def test_save_template_unknown_returns_404(self):
        """POST /api/templates/nope.j2 returns 404."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/nope.j2",
            json={"content": "# X"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 404)

    # --- preview ---

    @unittest.mock.patch(
        "oden.web_handlers.template_handlers.render_template_from_string",
        return_value="rendered output",
    )
    @unittest.mock.patch("oden.web_handlers.template_handlers.validate_template", return_value=(True, None))
    async def test_preview_template_success(self, mock_val, mock_render):
        """POST /api/templates/report.md.j2/preview returns rendered preview."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/report.md.j2/preview",
            json={"content": "# {{ tnr }}"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["preview"], "rendered output")

    @unittest.mock.patch(
        "oden.web_handlers.template_handlers.validate_template",
        return_value=(False, "unexpected '}'"),
    )
    async def test_preview_template_syntax_error(self, mock_val):
        """POST preview with invalid syntax returns error (but 200)."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/report.md.j2/preview",
            json={"content": "{{ bad }"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertFalse(data["success"])
        self.assertIn("Mallsyntaxfel", data["error"])

    async def test_preview_template_empty_returns_400(self):
        """POST preview with empty content returns 400."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/report.md.j2/preview",
            json={"content": ""},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)

    async def test_preview_template_unknown_returns_404(self):
        """POST /api/templates/nope.j2/preview returns 404."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/nope.j2/preview",
            json={"content": "# X"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 404)

    # --- reset ---

    @unittest.mock.patch("oden.web_handlers.template_handlers.save_template_content", return_value=True)
    @unittest.mock.patch(
        "oden.web_handlers.template_handlers.load_template_from_file",
        return_value="# Default",
    )
    async def test_reset_template_success(self, mock_load, mock_save):
        """POST /api/templates/report.md.j2/reset restores default."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/report.md.j2/reset",
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["content"], "# Default")

    @unittest.mock.patch(
        "oden.web_handlers.template_handlers.load_template_from_file",
        side_effect=FileNotFoundError,
    )
    async def test_reset_template_file_not_found(self, mock_load):
        """POST reset when default file missing returns 500."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/report.md.j2/reset",
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 500)
        data = await resp.json()
        self.assertFalse(data["success"])

    async def test_reset_template_unknown_returns_404(self):
        """POST /api/templates/nope.j2/reset returns 404."""
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/templates/nope.j2/reset",
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 404)

    # --- export ---

    @unittest.mock.patch("oden.web_handlers.template_handlers.get_template_content", return_value="# TPL")
    async def test_export_template_success(self, mock_get):
        """GET /api/templates/report.md.j2/export returns file download."""
        token = await self._get_valid_token()
        resp = await self.client.get("/api/templates/report.md.j2/export", headers=self._auth_header(token))
        self.assertEqual(resp.status, 200)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))
        body = await resp.text()
        self.assertEqual(body, "# TPL")

    async def test_export_template_unknown_returns_404(self):
        """GET /api/templates/nope.j2/export returns 404."""
        token = await self._get_valid_token()
        resp = await self.client.get("/api/templates/nope.j2/export", headers=self._auth_header(token))
        self.assertEqual(resp.status, 404)

    # --- export all (ZIP) ---

    @unittest.mock.patch("oden.web_handlers.template_handlers.get_template_content", return_value="# TPL")
    async def test_export_all_templates_zip(self, mock_get):
        """GET /api/templates/export returns a valid ZIP file."""
        import zipfile as zf

        token = await self._get_valid_token()
        resp = await self.client.get("/api/templates/export", headers=self._auth_header(token))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "application/zip")
        body = await resp.read()
        # Verify it's a valid ZIP containing both templates
        import io

        with zf.ZipFile(io.BytesIO(body)) as z:
            self.assertIn("report.md.j2", z.namelist())
            self.assertIn("append.md.j2", z.namelist())


# ---------------------------------------------------------------------------
# INI import / export tests
# ---------------------------------------------------------------------------


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


class TestGroupsHandlerResponse(AioHTTPTestCase):
    """Test that groups_handler returns whitelist and ignore lists correctly."""

    async def get_application(self):
        return create_app(setup_mode=False)

    @unittest.mock.patch("oden.web_handlers.group_handlers.cfg")
    async def test_groups_response_includes_whitelist(self, mock_cfg):
        """groups_handler returns whitelistGroups from config."""
        mock_cfg.IGNORED_GROUPS = []
        mock_cfg.WHITELIST_GROUPS = ["Alpha", "Bravo"]
        from oden.app_state import get_app_state

        app_state = get_app_state()
        app_state.update_groups(
            [
                {"id": "1", "name": "Alpha", "isMember": True, "members": []},
                {"id": "2", "name": "Bravo", "isMember": True, "members": []},
                {"id": "3", "name": "Charlie", "isMember": True, "members": []},
            ]
        )

        resp = await self.client.get("/api/groups")
        data = await resp.json()
        self.assertEqual(data["whitelistGroups"], ["Alpha", "Bravo"])
        self.assertEqual(data["ignoredGroups"], [])
        # All 3 groups should be in the list regardless of whitelist
        group_names = [g["name"] for g in data["groups"]]
        self.assertIn("Alpha", group_names)
        self.assertIn("Bravo", group_names)
        self.assertIn("Charlie", group_names)

        # Clean up
        app_state.update_groups([])


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
