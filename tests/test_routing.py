"""Routing (vägval + grenar): model, migration from the old chain, and the orchestrator."""

import copy
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from oden.config_db import init_db
from oden.flow_db import get_flow_item
from oden.messages_db import create_raw_message
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.pipeline_settings import is_group_filtered
from oden.routing import (
    derive_from_legacy,
    message_source,
    normalize_routing,
    resolve_branch,
    step_settings,
)

CHAIN = ["group_filter", "seven_s", "fors", "pedars", "scrim", "generic_template"]


def _msg(group=None, *, tak=False, group_id=None):
    dm = {"message": "hej"}
    if group or group_id:
        dm["groupV2"] = {"id": group_id or f"id-{group}", "name": group}
    env = {"sourceNumber": "tak:X" if tak else "+46701111111", "timestamp": 1, "dataMessage": dm}
    if tak:
        env["_source"] = "tak"
    return {"envelope": env}


class DeriveFromLegacyTest(unittest.TestCase):
    """The migrated routing must send every message where the old chain did."""

    def _same_as_old_filter(self, mode, groups, messages):
        settings = {"group_filter": {"mode": mode, "groups": groups}}
        routing = derive_from_legacy(CHAIN, settings)
        for msg in messages:
            src = message_source(msg)
            old_ignored = is_group_filtered(src["group_name"], settings)
            branch, _ = resolve_branch(routing, msg)
            self.assertEqual(branch["ignore"], old_ignored, (mode, src))

    def test_blacklist_matches_old_behaviour(self):
        self._same_as_old_filter(
            "blacklist",
            ["Kaffe", "TAK"],
            [_msg("Kaffe"), _msg("Spaning"), _msg(), _msg("TAK", tak=True), _msg("Annat", tak=True)],
        )

    def test_whitelist_matches_old_behaviour(self):
        self._same_as_old_filter(
            "whitelist",
            ["Spaning"],
            [_msg("Kaffe"), _msg("Spaning"), _msg(), _msg("TAK", tak=True)],
        )

    def test_filter_without_groups_or_disabled_routes_everything_to_main(self):
        for chain, groups in ((CHAIN, []), ([n for n in CHAIN if n != "group_filter"], ["Kaffe"])):
            routing = derive_from_legacy(chain, {"group_filter": {"mode": "blacklist", "groups": groups}})
            self.assertEqual(routing["assign"], {})
            self.assertFalse(resolve_branch(routing, _msg("Kaffe"))[0]["ignore"])

    def test_chain_order_and_fallback_are_kept(self):
        routing = derive_from_legacy(["scrim", "group_filter", "seven_s"], {})
        main = routing["branches"][0]
        self.assertEqual([s["pipeline"] for s in main["steps"]], ["scrim", "seven_s", "generic_template"])


class NormalizeRoutingTest(unittest.TestCase):
    def _base(self, **over):
        return {
            "branches": [
                {"id": "spaning", "name": "Spaning", "steps": ["seven_s"]},
                {"id": "ign", "name": "Ignorera", "ignore": True, "steps": ["seven_s"]},
            ],
            "assign": {"group:Kaffe": "ign"},
            "default": "spaning",
            **over,
        }

    def test_fallback_is_appended_and_ignore_has_no_steps(self):
        routing = normalize_routing(self._base())
        self.assertEqual([s["pipeline"] for s in routing["branches"][0]["steps"]], ["seven_s", "generic_template"])
        self.assertEqual(routing["branches"][1]["steps"], [])

    def test_unknown_pipelines_and_duplicates_are_dropped(self):
        routing = normalize_routing(
            self._base(branches=[{"id": "a", "name": "A", "steps": ["seven_s", "seven_s", "rm -rf", "group_filter"]}])
            | {"assign": {}, "default": "a"}
        )
        self.assertEqual([s["pipeline"] for s in routing["branches"][0]["steps"]], ["seven_s", "generic_template"])

    def test_rejects_bad_references(self):
        for bad in (
            self._base(default="nope"),
            self._base(assign={"group:X": "nope"}),
            self._base(assign={"somewhere": "spaning"}),
            self._base(branches=[]),
            self._base(branches=[{"id": "a", "name": "A"}, {"id": "a", "name": "B"}], default="a", assign={}),
        ):
            with self.assertRaises(ValueError):
                normalize_routing(bad)

    def test_ids_are_generated_from_names(self):
        routing = normalize_routing(
            {"branches": [{"name": "Underhåll"}, {"name": "Underhåll"}], "assign": {}, "default": "underhall"}
        )
        self.assertEqual([b["id"] for b in routing["branches"]], ["underhall", "underhall-2", "ignore"])

    def test_an_ignore_choice_always_exists(self):
        routing = normalize_routing(
            {"branches": [{"id": "ignore", "name": "Ignore"}], "assign": {}, "default": "ignore"}
        )
        self.assertEqual([(b["id"], b["ignore"]) for b in routing["branches"]], [("ignore", False), ("ignorera", True)])
        kept = normalize_routing(self._base())
        self.assertEqual(sum(b["ignore"] for b in kept["branches"]), 1)


class ResolveBranchTest(unittest.TestCase):
    def setUp(self):
        self.routing = normalize_routing(
            {
                "branches": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}, {"id": "c", "name": "C"}],
                "assign": {"source:tak": "b", "group_id:gid-1": "c", "group:Spaning": "a", "source:direct": "b"},
                "default": "a",
            }
        )

    def test_order_tak_then_group_id_then_name_then_direct_then_default(self):
        self.assertEqual(resolve_branch(self.routing, _msg("Spaning", tak=True))[0]["id"], "b")
        self.assertEqual(resolve_branch(self.routing, _msg("Spaning", group_id="gid-1"))[0]["id"], "c")
        self.assertEqual(resolve_branch(self.routing, _msg("Spaning"))[0]["id"], "a")
        self.assertEqual(resolve_branch(self.routing, _msg())[0]["id"], "b")
        branch, reason = resolve_branch(self.routing, _msg("Okänd"))
        self.assertEqual(branch["id"], "a")
        self.assertIn("standardgrenen", reason)


class GroupBranchTest(unittest.TestCase):
    def test_group_branch_by_id_then_name_else_default(self):
        from oden.routing import group_branch

        routing = normalize_routing(
            {
                "branches": [{"id": "a", "name": "A"}, {"id": "ign", "name": "Ignorera", "ignore": True}],
                "assign": {"group_id:g1": "ign", "group:Kaffe": "ign"},
                "default": "a",
            }
        )
        self.assertEqual(group_branch(routing, "g1", "Annat namn")[0]["id"], "ign")
        self.assertEqual(group_branch(routing, "g2", "Kaffe"), (routing["branches"][1], True))
        self.assertEqual(group_branch(routing, "g3", "Spaning"), (routing["branches"][0], False))


class _SubdirProbe:
    """Handles every message and remembers the vault_subdir it saw."""

    name = "seven_s"
    seen: list = []

    async def run(self, *, msg_data, reader, writer):
        from oden import config as cfg

        _SubdirProbe.seen.append(step_settings(self.name, cfg.PIPELINE_SETTINGS).get("vault_subdir"))
        return True


class OrchestratorRoutingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "config.db"
        init_db(self.db)
        routing = {
            "branches": [
                {
                    "id": "spaning",
                    "name": "Spaning",
                    "steps": [{"pipeline": "seven_s", "config": {"vault_subdir": "Spaning/7S"}}],
                },
                {"id": "ovning", "name": "Övning", "steps": ["seven_s"]},
                {"id": "ign", "name": "Ignorera", "ignore": True},
            ],
            "assign": {"group:Spaning Norr": "spaning", "group:Kaffe": "ign"},
            "default": "ovning",
        }
        patches = [
            unittest.mock.patch("oden.pipeline_orchestrator.cfg.ROUTING", routing),
            unittest.mock.patch(
                "oden.pipeline_orchestrator.cfg.PIPELINE_SETTINGS", {"seven_s": {"vault_subdir": "Global"}}
            ),
            unittest.mock.patch("oden.pipeline_orchestrator.get_tak_bridge", return_value=None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.orchestrator = PipelineOrchestrator(self.db)
        self.orchestrator._pipeline_map["seven_s"] = _SubdirProbe()
        _SubdirProbe.seen = []

    async def _run(self, msg):
        message_id = create_raw_message(self.db, "+46700000000", msg)
        await self.orchestrator.run_message(message_id=message_id, msg_data=msg, reader=None, writer=None)
        return get_flow_item(self.db, message_id)

    async def test_ignore_branch_stores_but_runs_nothing(self):
        item = await self._run(_msg("Kaffe"))
        self.assertEqual(item["status"], "ignored")
        self.assertEqual(item["branch"], "ign")
        self.assertEqual([s["pipeline"] for s in item["steps"]], ["router"])
        self.assertEqual(item["steps"][0]["outcome"], "ignored")
        self.assertIn("Ignorera", item["steps"][0]["reason"])
        self.assertEqual(_SubdirProbe.seen, [])

    async def test_step_config_overrides_global_settings_per_branch(self):
        spaning = await self._run(_msg("Spaning Norr"))
        ovning = await self._run(_msg("Annan grupp"))
        self.assertEqual(_SubdirProbe.seen, ["Spaning/7S", "Global"])
        self.assertEqual(spaning["branch_name"], "Spaning")
        self.assertEqual(spaning["steps"][0]["outcome"], "route")
        self.assertEqual(ovning["branch"], "ovning")

    async def test_step_config_does_not_leak_after_the_run(self):
        from oden import config as cfg

        await self._run(_msg("Spaning Norr"))
        self.assertEqual(step_settings("seven_s", cfg.PIPELINE_SETTINGS).get("vault_subdir"), "Global")

    async def test_unassigned_group_is_marked_in_flow(self):
        assigned = await self._run(_msg("Spaning Norr"))
        unassigned = await self._run(_msg("Annan grupp"))
        direct = await self._run(_msg())
        self.assertFalse(assigned["unassigned_group"])
        self.assertTrue(unassigned["unassigned_group"])
        self.assertFalse(direct["unassigned_group"])

    async def test_flow_filters_and_step_stats_follow_the_branch(self):
        from oden.flow_db import list_flow
        from oden.web_handlers.routing_handlers import _step_stats

        spaning = await self._run(_msg("Spaning Norr"))
        await self._run(_msg("Annan grupp"))
        await self._run(_msg("Kaffe"))

        self.assertEqual([m["id"] for m in list_flow(self.db, branch="spaning")], [spaning["id"]])
        self.assertEqual(len(list_flow(self.db, branch="ign")), 1)
        self.assertEqual(len(list_flow(self.db, pipeline="seven_s", outcome="handled")), 2)
        self.assertEqual(list_flow(self.db, pipeline="seven_s", outcome="failed"), [])

        stats = _step_stats(self.db)
        self.assertEqual(stats["spaning"]["seven_s"]["handled"], 1)
        self.assertEqual(stats["ovning"]["seven_s"]["handled"], 1)
        self.assertNotIn("ign", stats)


class MigrateRoutingTest(unittest.TestCase):
    def test_stores_derived_routing_once(self):
        from oden.config import _migrate_routing

        app_config = {
            "enabled_pipelines": CHAIN,
            "pipeline_settings": {"group_filter": {"mode": "blacklist", "groups": ["Kaffe"]}},
        }
        with unittest.mock.patch("oden.config_db.set_config_value") as save:
            _migrate_routing(app_config)
            _migrate_routing(app_config)
        save.assert_called_once()
        self.assertEqual(app_config["routing"]["assign"], {"group:Kaffe": "ignore"})


class RoutingApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_and_put(self):
        from aiohttp.test_utils import TestClient, TestServer

        from oden.config_db import get_all_config
        from oden.web_server import create_app

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "config.db"
            init_db(db)
            legacy = {"group_filter": {"mode": "blacklist", "groups": ["Kaffe"]}}
            with (
                unittest.mock.patch("oden.config.CONFIG_DB", db),
                unittest.mock.patch("oden.config.ROUTING", None),
                unittest.mock.patch("oden.config.ENABLED_PIPELINES", CHAIN),
                unittest.mock.patch("oden.config.PIPELINE_SETTINGS", legacy),
            ):
                async with TestClient(TestServer(create_app())) as client:
                    data = await (await client.get("/api/routing")).json()
                    routing = copy.deepcopy(data["routing"])
                    routing["branches"].append({"name": "Spaning", "steps": ["seven_s"]})
                    routing["assign"]["source:tak"] = "spaning"
                    saved = await client.put("/api/routing", json={"routing": routing})
                    bad = await client.put("/api/routing", json={"routing": {**routing, "default": "nope"}})
                    bad_error = (await bad.json())["error"]
                    page = await (await client.get("/")).text()
                    stored = get_all_config(db)["routing"]

        self.assertEqual([b["id"] for b in data["routing"]["branches"]], ["main", "ignore"])
        kaffe = next(s for s in data["sources"] if s["key"] == "group:Kaffe")
        self.assertEqual(kaffe["branch"], "ignore")
        self.assertTrue(kaffe["assigned"])
        self.assertIn("seven_s", [p["name"] for p in data["pipelines"]])
        self.assertFalse(data["publish_to_tak"])
        self.assertIn("step_stats_24h", data)
        self.assertNotIn("group_filter", [p["name"] for p in data["pipelines"]])
        self.assertEqual(saved.status, 200)
        self.assertEqual(stored["assign"]["source:tak"], "spaning")
        self.assertEqual(bad.status, 400)
        self.assertIn("Standardgrenen", bad_error)
        self.assertIn('id="routing-sources"', page)
        self.assertIn('id="routing-columns"', page)
        self.assertIn("function showFlowFiltered", page)
        self.assertIn("function assignSource", page)
