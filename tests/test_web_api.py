"""Web GUI API endpoint and authentication tests.

Tests use aiohttp's built-in test client (no browser needed).
"""

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
        resp = await self.client.get("/api/token")
        token = (await resp.json())["token"]
        resp = await self.client.get("/api/groups", headers={"Authorization": f"Bearer {token}"})
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

    async def test_protected_groups_rejects_without_token(self):
        resp = await self.client.get("/api/groups")
        self.assertEqual(resp.status, 401)

    async def test_refresh_groups_rejects_without_token(self):
        resp = await self.client.post("/api/groups/refresh")
        self.assertEqual(resp.status, 401)

    async def test_unprotected_invitations_works_without_token(self):
        resp = await self.client.get("/api/invitations")
        self.assertEqual(resp.status, 200)

    # ------------------------------------------------------------------
    # /api/accounts/link (protected)
    # ------------------------------------------------------------------
    async def test_accounts_link_rejects_without_token(self):
        resp = await self.client.post("/api/accounts/link", json={})
        self.assertEqual(resp.status, 401)

    async def test_accounts_link_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/accounts/link",
            json={},
            headers=self._auth_header(token),
        )
        # Will return 503 (not connected) but not 401
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/accounts/link-cancel (protected)
    # ------------------------------------------------------------------
    async def test_accounts_link_cancel_rejects_without_token(self):
        resp = await self.client.post("/api/accounts/link-cancel")
        self.assertEqual(resp.status, 401)

    async def test_accounts_link_cancel_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/accounts/link-cancel",
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/accounts/activate (protected)
    # ------------------------------------------------------------------
    async def test_accounts_activate_rejects_without_token(self):
        resp = await self.client.post(
            "/api/accounts/activate",
            json={"number": "+46700000000"},
        )
        self.assertEqual(resp.status, 401)

    async def test_accounts_activate_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/accounts/activate",
            json={"number": "+46700000000"},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/accounts/{number} DELETE (prefix-protected)
    # ------------------------------------------------------------------
    async def test_accounts_delete_rejects_without_token(self):
        resp = await self.client.delete("/api/accounts/+46700000000")
        self.assertEqual(resp.status, 401)

    async def test_accounts_delete_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.delete(
            "/api/accounts/+46700000000",
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/accounts/{number}/force DELETE (prefix-protected)
    # ------------------------------------------------------------------
    async def test_accounts_force_delete_rejects_without_token(self):
        resp = await self.client.delete("/api/accounts/+46700000000/force")
        self.assertEqual(resp.status, 401)

    async def test_accounts_force_delete_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.delete(
            "/api/accounts/+46700000000/force",
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/accounts/link-status (prefix-protected)
    # ------------------------------------------------------------------
    async def test_accounts_link_status_rejects_without_token(self):
        resp = await self.client.get("/api/accounts/link-status")
        self.assertEqual(resp.status, 401)

    async def test_accounts_link_status_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.get(
            "/api/accounts/link-status",
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/accounts (unprotected — GET list)
    # ------------------------------------------------------------------
    async def test_unprotected_accounts_list_works_without_token(self):
        resp = await self.client.get("/api/accounts")
        self.assertEqual(resp.status, 200)

    # ------------------------------------------------------------------
    # /api/config/reset (protected)
    # ------------------------------------------------------------------
    async def test_config_reset_rejects_without_token(self):
        resp = await self.client.delete("/api/config/reset")
        self.assertEqual(resp.status, 401)

    async def test_config_reset_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.delete(
            "/api/config/reset",
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/contacts (unprotected — GET list)
    # ------------------------------------------------------------------
    async def test_unprotected_contacts_works_without_token(self):
        resp = await self.client.get("/api/contacts")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("contacts", data)

    # ------------------------------------------------------------------
    # /api/contacts/refresh (protected)
    # ------------------------------------------------------------------
    async def test_contacts_refresh_rejects_without_token(self):
        resp = await self.client.post("/api/contacts/refresh")
        self.assertEqual(resp.status, 401)

    async def test_contacts_refresh_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/contacts/refresh",
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/accounts/devices (prefix-protected via /api/accounts/)
    # ------------------------------------------------------------------
    async def test_accounts_devices_rejects_without_token(self):
        resp = await self.client.get("/api/accounts/devices")
        self.assertEqual(resp.status, 401)

    async def test_accounts_devices_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.get(
            "/api/accounts/devices",
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/signal-config GET (protected)
    # ------------------------------------------------------------------
    async def test_signal_config_get_rejects_without_token(self):
        resp = await self.client.get("/api/signal-config")
        self.assertEqual(resp.status, 401)

    async def test_signal_config_get_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.get(
            "/api/signal-config",
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("typingIndicators", data)

    # ------------------------------------------------------------------
    # /api/signal-config POST (protected)
    # ------------------------------------------------------------------
    async def test_signal_config_save_rejects_without_token(self):
        resp = await self.client.post("/api/signal-config", json={"typingIndicators": True})
        self.assertEqual(resp.status, 401)

    async def test_signal_config_save_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/signal-config",
            json={"typingIndicators": False},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # /api/groups/update (protected)
    # ------------------------------------------------------------------
    async def test_update_group_rejects_without_token(self):
        resp = await self.client.post(
            "/api/groups/update",
            json={"groupId": "test-id", "name": "New Name"},
        )
        self.assertEqual(resp.status, 401)

    async def test_update_group_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/groups/update",
            json={"groupId": "test-id", "name": "New Name"},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    async def test_update_group_rejects_missing_group_id(self):
        token = await self._get_valid_token()
        resp = await self.client.post(
            "/api/groups/update",
            json={"name": "New Name"},
            headers=self._auth_header(token),
        )
        self.assertEqual(resp.status, 400)

    # ------------------------------------------------------------------
    # /api/contacts/{number} PUT (prefix-protected via /api/contacts/)
    # ------------------------------------------------------------------
    async def test_update_contact_rejects_without_token(self):
        resp = await self.client.put(
            "/api/contacts/+46700000000",
            json={"givenName": "Test"},
        )
        self.assertEqual(resp.status, 401)

    async def test_update_contact_accepts_valid_token(self):
        token = await self._get_valid_token()
        resp = await self.client.put(
            "/api/contacts/+46700000000",
            json={"givenName": "Test"},
            headers=self._auth_header(token),
        )
        self.assertNotEqual(resp.status, 401)
        self.assertNotEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # Token renewal after server restart
    # ------------------------------------------------------------------
    async def test_stale_token_rejected_fresh_token_works(self):
        """Simulate a server restart: old token fails, fresh /api/token works.

        This mirrors the client-side authenticatedFetch retry logic — on 401
        the JS clears the cached token, re-fetches from /api/token, and
        retries.
        """
        import oden.web_server as ws

        original_api_token = ws._api_token
        try:
            # Get a valid token
            valid_token = await self._get_valid_token()
            resp = await self.client.get("/api/groups", headers=self._auth_header(valid_token))
            self.assertEqual(resp.status, 200)

            # Simulate server restart by forcing a new token
            old_token = ws._api_token
            ws._api_token = None  # reset so next get_api_token() generates fresh

            # Old token should now be rejected
            resp = await self.client.get("/api/groups", headers=self._auth_header(old_token))
            self.assertEqual(resp.status, 401)

            # Fetching /api/token gives the new token, which works
            resp = await self.client.get("/api/token")
            new_token = (await resp.json())["token"]
            self.assertNotEqual(new_token, old_token)
            resp = await self.client.get("/api/groups", headers=self._auth_header(new_token))
            self.assertEqual(resp.status, 200)
        finally:
            ws._api_token = original_api_token

    # ------------------------------------------------------------------
    # Dashboard JS includes authenticatedFetch with retry logic
    # ------------------------------------------------------------------
    async def test_dashboard_js_has_authenticated_fetch(self):
        """Verify that the dashboard JS includes the authenticatedFetch
        function that handles 401 retry with token refresh."""
        resp = await self.client.get("/")
        text = await resp.text()
        self.assertIn("async function authenticatedFetch(", text)
        self.assertIn("if (response.status === 401)", text)
        self.assertIn("/api/token", text)
