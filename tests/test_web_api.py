"""Web GUI API endpoint tests.

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
