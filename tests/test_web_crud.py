"""Web GUI CRUD tests — responses, templates, groups.

Tests use aiohttp's built-in test client (no browser needed).
"""

import unittest
import unittest.mock

from aiohttp.test_utils import AioHTTPTestCase

from oden.web_server import create_app


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

    @unittest.mock.patch("oden.web_handlers._helpers.reload_config")
    @unittest.mock.patch("oden.web_handlers._helpers.set_config_value")
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

    @unittest.mock.patch("oden.web_handlers._helpers.reload_config")
    @unittest.mock.patch("oden.web_handlers._helpers.set_config_value")
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

    @unittest.mock.patch("oden.web_handlers._helpers.reload_config")
    @unittest.mock.patch("oden.web_handlers._helpers.set_config_value")
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

    @unittest.mock.patch("oden.web_handlers._helpers.reload_config")
    @unittest.mock.patch("oden.web_handlers._helpers.set_config_value")
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
        import io
        import zipfile as zf

        token = await self._get_valid_token()
        resp = await self.client.get("/api/templates/export", headers=self._auth_header(token))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "application/zip")
        body = await resp.read()
        # Verify it's a valid ZIP containing both templates
        with zf.ZipFile(io.BytesIO(body)) as z:
            self.assertIn("report.md.j2", z.namelist())
            self.assertIn("append.md.j2", z.namelist())


class TestGroupsHandlerResponse(AioHTTPTestCase):
    """Test that groups_handler returns whitelist and ignore lists correctly."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def _get_valid_token(self) -> str:
        resp = await self.client.get("/api/token")
        data = await resp.json()
        return data["token"]

    def _auth_header(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    @unittest.mock.patch("oden.web_handlers.group_handlers.get_all_groups", return_value=[])
    @unittest.mock.patch("oden.web_handlers.group_handlers.cfg")
    async def test_groups_response_includes_whitelist(self, mock_cfg, _mock_db):
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

        token = await self._get_valid_token()
        resp = await self.client.get("/api/groups", headers=self._auth_header(token))
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

    @unittest.mock.patch("oden.web_handlers.group_handlers.cfg")
    @unittest.mock.patch("oden.web_handlers.group_handlers.get_all_groups")
    async def test_groups_merges_db_and_cache(self, mock_db_groups, mock_cfg):
        """groups_handler merges DB groups with in-memory cache."""
        mock_cfg.IGNORED_GROUPS = []
        mock_cfg.WHITELIST_GROUPS = []
        # DB has a group discovered from a message (no member info)
        mock_db_groups.return_value = [
            {"id": "db1", "name": "DB Only", "memberCount": 0, "isMember": True},
        ]
        from oden.app_state import get_app_state

        app_state = get_app_state()
        # Cache has a different group from listGroups RPC
        app_state.update_groups(
            [
                {
                    "id": "rpc1",
                    "name": "RPC Group",
                    "isMember": True,
                    "members": [{"number": "+461", "role": "DEFAULT"}, {"number": "+462", "role": "DEFAULT"}],
                }
            ]
        )

        token = await self._get_valid_token()
        resp = await self.client.get("/api/groups", headers=self._auth_header(token))
        data = await resp.json()
        names = {g["name"] for g in data["groups"]}
        self.assertIn("DB Only", names)
        self.assertIn("RPC Group", names)
        self.assertEqual(len(data["groups"]), 2)

        app_state.update_groups([])
