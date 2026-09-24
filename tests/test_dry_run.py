"""Testruta: the dry run shows the route and the would-be file, and changes nothing."""

import sqlite3
import tempfile
import unittest
import unittest.mock
import zoneinfo
from pathlib import Path

from oden.config_db import init_db
from oden.dry_run import build_test_message, dry_run
from oden.routing import normalize_routing

SEVEN_S = (
    "7S RAPPORT\nFrån: Pluton 1\nTill: Stab\nTNR: 241430\nStund: 241430\nStälle: 33V VN 12345 67890\n"
    "Styrka: 4\nSlag: okänd\nSysselsättning: rör sig\nSymbol: bil\nSagesman: egen obs"
)

ROUTING = normalize_routing(
    {
        "branches": [
            {
                "id": "spaning",
                "name": "Spaning",
                "steps": [
                    {"pipeline": "seven_s", "config": {"vault_subdir": "Spaning/7S", "vault_subdir_enabled": True}}
                ],
            },
            {"id": "ign", "name": "Ignorera", "ignore": True},
        ],
        "assign": {"group:Kaffe": "ign"},
        "default": "spaning",
    }
)


class DryRunTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name) / "vault"
        self.vault.mkdir()
        self.db = Path(tmp.name) / "config.db"
        init_db(self.db)
        patches = [
            unittest.mock.patch("oden.config.VAULT_PATH", str(self.vault)),
            unittest.mock.patch("oden.config.CONFIG_DB", self.db),
            unittest.mock.patch("oden.config.ROUTING", ROUTING),
            unittest.mock.patch("oden.config.GROUP_SPLIT_ENABLED", True),
            unittest.mock.patch("oden.config.TIMEZONE", zoneinfo.ZoneInfo("Europe/Stockholm")),
            unittest.mock.patch("oden.config.PIPELINE_SETTINGS", {}),
            unittest.mock.patch("oden.dry_run.publish_to_tak", return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _nothing_changed(self):
        self.assertEqual(list(self.vault.iterdir()), [])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0], 0)

    async def test_report_is_previewed_in_the_branch_subdir_without_writing(self):
        result = await dry_run(build_test_message(SEVEN_S, "group:Spaning Norr"))
        self.assertEqual(result["branch"], "spaning")
        self.assertFalse(result["assigned"])
        self.assertEqual(result["handled_by"], "seven_s")
        self.assertEqual(result["output_file"], "Spaning Norr/Spaning/7S/TNR241430.md")
        self.assertIn("**Styrka:** 4", result["content"])
        self.assertTrue(result["steps"][0]["warnings"], "the non-canonical sagesman warning is shown")
        self.assertEqual([s["outcome"] for s in result["steps"]], ["handled", "notrun"])
        self._nothing_changed()

    async def test_plain_text_falls_through_to_the_fallback(self):
        result = await dry_run(build_test_message("Framme vid samlingsplats", "group:Pluton 3"))
        self.assertEqual([s["outcome"] for s in result["steps"]], ["skipped", "handled"])
        self.assertIn("Ingen rubrik", result["steps"][0]["reason"])
        self.assertEqual(result["handled_by"], "generic_template")
        self.assertTrue(result["output_file"].startswith("Pluton 3/"))
        self.assertIn("Framme vid samlingsplats", result["content"])
        self._nothing_changed()

    async def test_ignore_branch_runs_no_steps(self):
        result = await dry_run(build_test_message("hej", "group:Kaffe"))
        self.assertTrue(result["ignore"])
        self.assertTrue(result["assigned"])
        self.assertEqual(result["steps"], [])
        self.assertIn("Ignorera", result["route_reason"])

    async def test_direct_message_is_not_saved(self):
        result = await dry_run(build_test_message("hej", "source:direct"))
        self.assertEqual(result["steps"][-1]["outcome"], "skipped")
        self.assertIn("Direktmeddelanden", result["steps"][-1]["reason"])
        self.assertIsNone(result["content"])
        self._nothing_changed()

    async def test_invalid_report_fails_the_step_and_continues(self):
        result = await dry_run(build_test_message("7S RAPPORT\nFrån: x", "group:Spaning Norr"))
        self.assertEqual(result["steps"][0]["outcome"], "failed")
        self.assertEqual(result["handled_by"], "generic_template")
        self._nothing_changed()

    async def test_api(self):
        from aiohttp.test_utils import TestClient, TestServer

        from oden.web_server import create_app

        async with TestClient(TestServer(create_app())) as client:
            ok = await client.post("/api/pipelines/test", json={"text": SEVEN_S, "source": "group:Spaning Norr"})
            ok_data = await ok.json()
            empty = await client.post("/api/pipelines/test", json={"text": "  ", "source": "source:direct"})
            bad = await client.post("/api/pipelines/test", json={"text": "hej", "source": "nowhere"})
        self.assertEqual(ok.status, 200)
        self.assertEqual(ok_data["handled_by"], "seven_s")
        self.assertEqual(empty.status, 400)
        self.assertEqual(bad.status, 400)
        self._nothing_changed()
