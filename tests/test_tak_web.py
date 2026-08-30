"""TAK web GUI endpoint tests."""

import tempfile
import unittest.mock
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from oden.config_db import get_config_value, init_db
from oden.web_server import create_app


class TestTakEndpoints(AioHTTPTestCase):
    async def get_application(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            self.db_path = Path(tmp.name)
        self.db_path.unlink(missing_ok=True)
        init_db(self.db_path)
        self._patch = unittest.mock.patch("oden.config.CONFIG_DB", self.db_path)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(lambda: self.db_path.unlink(missing_ok=True))
        return create_app(setup_mode=False)

    async def test_status_reports_disabled_by_default(self):
        resp = await self.client.get("/api/tak/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertFalse(data["enabled"])
        self.assertFalse(data["connected"])

    async def test_settings_never_expose_a_password(self):
        resp = await self.client.get("/api/tak/settings")
        data = await resp.json()
        self.assertNotIn("tls_client_password", data)
        self.assertIn("tls_client_password_env", data)

    async def test_save_roundtrips_and_splits_comma_lists(self):
        resp = await self.client.post(
            "/api/tak/settings",
            json={
                "enabled": True,
                "cot_url": "tls://tak.example.mil:8089",
                "cot_stale_seconds": 600,
                "inbound_types": "a-h-*, a-u-*",
            },
        )
        self.assertEqual(resp.status, 200)
        self.assertTrue((await resp.json())["success"])

        stored = get_config_value(self.db_path, "tak_settings")
        self.assertEqual(stored["cot_url"], "tls://tak.example.mil:8089")
        self.assertEqual(stored["cot_stale_seconds"], 600)
        self.assertEqual(stored["inbound_types"], ["a-h-*", "a-u-*"])
        # no lifecycle loop under the test client -> no reconnect attempt
        self.assertIn("Starta om Oden", (await resp.json())["message"])

    async def test_save_hot_reloads_when_lifecycle_is_running(self):
        calls = []

        async def fake_stop():
            calls.append("stop")

        async def fake_start():
            calls.append("start")

        with (
            unittest.mock.patch("oden.app_state.get_app_state", return_value=unittest.mock.Mock(loop=object())),
            unittest.mock.patch("oden.tak.bridge.stop_tak_bridge", fake_stop),
            unittest.mock.patch("oden.tak.bridge.start_tak_bridge", fake_start),
            unittest.mock.patch("oden.tak.bridge.get_tak_bridge", return_value=None),
        ):
            resp = await self.client.post("/api/tak/settings", json={"enabled": False, "cot_url": "tls://x:8089"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(calls, ["stop", "start"])
        self.assertIn("avstängt", (await resp.json())["message"])

    async def test_enabling_without_a_target_is_rejected(self):
        resp = await self.client.post("/api/tak/settings", json={"enabled": True, "cot_url": ""})
        self.assertEqual(resp.status, 400)
        self.assertFalse(get_config_value(self.db_path, "tak_settings").get("enabled"))

    async def test_zero_stale_is_rejected(self):
        resp = await self.client.post(
            "/api/tak/settings",
            json={"enabled": False, "cot_url": "tls://x:8089", "cot_stale_seconds": 0},
        )
        self.assertEqual(resp.status, 400)

    async def test_test_marker_needs_a_connected_bridge(self):
        resp = await self.client.post("/api/tak/test", json={"mgrs": "34VCM7934926095"})
        self.assertEqual(resp.status, 503)

    async def test_test_marker_publishes_when_connected(self):
        published = []

        class Bridge:
            is_running = True
            stale_seconds = 3600
            archive = True

            async def publish(self, cot):
                published.append(cot)
                return True

        with unittest.mock.patch("oden.web_handlers.tak_handlers.get_tak_bridge", return_value=Bridge()):
            resp = await self.client.post("/api/tak/test", json={"mgrs": "34VCM 79349 26095"})
            self.assertEqual(resp.status, 200)
            self.assertTrue((await resp.json())["success"])

            bad = await self.client.post("/api/tak/test", json={"mgrs": "inte en position"})
            self.assertEqual(bad.status, 400)

        self.assertEqual(len(published), 1)
        self.assertIn(b"ODEN.TEST.", published[0])
