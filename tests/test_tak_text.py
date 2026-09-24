"""TAK → text: the visible pre-step that makes text of a received CoT."""

import copy
import tempfile
import unittest
import unittest.mock
import zoneinfo
from pathlib import Path

from oden.config_db import init_db
from oden.dry_run import build_test_message, dry_run
from oden.flow_db import get_flow_item
from oden.messages_db import STATUS_IGNORED, create_raw_message
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.pipelines.tak_text import TakTextPipeline
from oden.routing import add_pre_step, normalize_routing, set_step_config
from oden.tak.cot import cot_to_inbound
from oden.tak.listener import build_envelope

_FIX = Path(__file__).parent / "fixtures" / "tak"
EIGHT_S = (_FIX / "8s_report.xml").read_bytes()
PLI = (_FIX / "friendly_pli.xml").read_bytes()
TZ = zoneinfo.ZoneInfo("Europe/Stockholm")


def _tak_message(xml: bytes) -> dict:
    return build_envelope(cot_to_inbound(xml), "TAK Inkommande", raw_xml=xml)


class _Tz(unittest.TestCase):
    def setUp(self):
        patch = unittest.mock.patch("oden.config.TIMEZONE", TZ)
        patch.start()
        self.addCleanup(patch.stop)


class TakTextStepTest(_Tz):
    def _convert(self, msg, **config):
        step = TakTextPipeline()
        token = set_step_config(config)
        try:
            with unittest.mock.patch("oden.config.PIPELINE_SETTINGS", {}):
                taken = step.convert(msg)
        finally:
            from oden.routing import reset_step_config

            reset_step_config(token)
        return step, taken

    def test_raw_cot_is_stored_with_the_message(self):
        msg = _tak_message(EIGHT_S)
        self.assertIn("<event", msg["envelope"]["_cot_xml"])
        self.assertTrue(msg["envelope"]["dataMessage"]["message"].startswith("7S RAPPORT"))

    def test_default_settings_give_exactly_the_text_stored_at_receipt(self):
        msg = _tak_message(EIGHT_S)
        step, taken = self._convert(copy.deepcopy(msg))
        self.assertFalse(taken)
        self.assertEqual(step.last_reason, "8S omgjord till 7S RAPPORT")
        self.assertEqual(
            step.last_transformed["envelope"]["dataMessage"]["message"], msg["envelope"]["dataMessage"]["message"]
        )

    def test_settings_change_the_text(self):
        msg = _tak_message(EIGHT_S)
        step, _ = self._convert(copy.deepcopy(msg), reshape_8s=False)
        self.assertTrue(step.last_transformed["envelope"]["dataMessage"]["message"].startswith("TAK-OBSERVATION"))
        self.assertIn("som TAK-OBSERVATION", step.last_reason)

        step, _ = self._convert(copy.deepcopy(msg), raw_block=False)
        text = step.last_transformed["envelope"]["dataMessage"]["message"]
        self.assertTrue(text.startswith("7S RAPPORT"))
        self.assertNotIn("%%", text)
        self.assertIn("utan rådatablocket", step.last_reason)

    def test_other_markers_can_be_skipped(self):
        step, taken = self._convert(_tak_message(PLI), other="skip")
        self.assertTrue(taken)
        self.assertEqual(step.status_on_handle, STATUS_IGNORED)
        self.assertIsNone(step.last_transformed)

    def test_signal_and_old_tak_messages_pass_through(self):
        step, taken = self._convert(build_test_message("hej", "group:G"))
        self.assertFalse(taken)
        self.assertIsNone(step.last_transformed)
        self.assertIn("Inte från TAK", step.last_reason)

        old = _tak_message(EIGHT_S)
        del old["envelope"]["_cot_xml"]
        step, taken = self._convert(old)
        self.assertIsNone(step.last_transformed)
        self.assertIn("Ingen rå CoT", step.last_reason)


class RoutingTest(unittest.TestCase):
    def test_pre_step_is_always_first(self):
        routing = normalize_routing(
            {"branches": [{"id": "a", "name": "A", "steps": ["seven_s", "tak_text"]}], "assign": {}, "default": "a"}
        )
        self.assertEqual(
            [s["pipeline"] for s in routing["branches"][0]["steps"]], ["tak_text", "seven_s", "generic_template"]
        )

    def test_migration_adds_the_step_where_tak_goes_once(self):
        from oden.config import _migrate_routing

        stored = {
            "version": 1,
            "branches": [
                {"id": "main", "name": "Huvud", "steps": ["seven_s"]},
                {"id": "tak", "name": "TAK", "steps": ["seven_s"]},
            ],
            "assign": {"source:tak": "tak"},
            "default": "main",
        }
        app_config = {"routing": copy.deepcopy(stored)}
        with unittest.mock.patch("oden.config_db.set_config_value") as save:
            _migrate_routing(app_config)
            steps = {b["id"]: [s["pipeline"] for s in b["steps"]] for b in app_config["routing"]["branches"]}
            self.assertEqual(steps["tak"][0], "tak_text")
            self.assertNotIn("tak_text", steps["main"])
            # The operator removes it again: it stays removed.
            app_config["routing"]["branches"][1]["steps"].pop(0)
            _migrate_routing(app_config)
        save.assert_called_once()
        self.assertNotIn("tak_text", [s["pipeline"] for s in app_config["routing"]["branches"][1]["steps"]])

    def test_add_pre_step_leaves_an_ignored_tak_alone(self):
        routing = normalize_routing(
            {"branches": [{"id": "a", "name": "A"}], "assign": {"source:tak": "ignore"}, "default": "a"}
        )
        routing = add_pre_step(routing)
        self.assertEqual(routing["version"], 2)
        self.assertNotIn("tak_text", [s["pipeline"] for b in routing["branches"] for s in b["steps"]])


class _Env(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name) / "vault"
        self.vault.mkdir()
        self.db = Path(tmp.name) / "config.db"
        init_db(self.db)
        self.routing = normalize_routing(
            {
                "branches": [
                    {"id": "tak", "name": "TAK", "steps": ["tak_text", "seven_s"]},
                    {
                        "id": "obs",
                        "name": "Observationer",
                        "steps": [{"pipeline": "tak_text", "config": {"reshape_8s": False}}, "seven_s"],
                    },
                ],
                "assign": {"source:tak": "tak"},
                "default": "tak",
            }
        )
        for patch in (
            unittest.mock.patch("oden.config.VAULT_PATH", str(self.vault)),
            unittest.mock.patch("oden.config.CONFIG_DB", self.db),
            unittest.mock.patch("oden.config.ROUTING", self.routing),
            unittest.mock.patch("oden.config.GROUP_SPLIT_ENABLED", True),
            unittest.mock.patch("oden.config.TIMEZONE", TZ),
            unittest.mock.patch("oden.config.PIPELINE_SETTINGS", {}),
            unittest.mock.patch("oden.pipeline_orchestrator.get_tak_bridge", return_value=None),
            unittest.mock.patch("oden.dry_run.publish_to_tak", return_value=False),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    async def _run(self, msg):
        message_id = create_raw_message(self.db, "+46700000000", msg)
        await PipelineOrchestrator(self.db).run_message(message_id=message_id, msg_data=msg, reader=None, writer=None)
        return get_flow_item(self.db, message_id)


class EndToEndTest(_Env):
    async def test_the_step_shows_in_flow_and_the_7s_is_written(self):
        item = await self._run(_tak_message(EIGHT_S))
        steps = [(s["pipeline"], s["outcome"]) for s in item["steps"]]
        self.assertEqual(steps[:3], [("router", "route"), ("tak_text", "transform"), ("seven_s", "handled")])
        self.assertEqual(item["steps"][1]["reason"], "8S omgjord till 7S RAPPORT")
        self.assertEqual(len(list(self.vault.rglob("TNR*.md"))), 1)

    async def test_branch_settings_change_what_the_steps_after_see(self):
        self.routing["assign"]["source:tak"] = "obs"
        item = await self._run(_tak_message(EIGHT_S))
        steps = {s["pipeline"]: s for s in item["steps"]}
        self.assertEqual(steps["tak_text"]["outcome"], "transform")
        self.assertEqual(steps["seven_s"]["outcome"], "skipped")
        self.assertEqual(steps["generic_template"]["outcome"], "handled")
        self.assertEqual(list(self.vault.rglob("TNR*.md")), [])

    async def test_testruta_takes_pasted_cot(self):
        result = await dry_run(build_test_message(EIGHT_S.decode(), "source:tak"))
        self.assertEqual([s["outcome"] for s in result["steps"][:2]], ["transform", "handled"])
        self.assertEqual(result["handled_by"], "seven_s")
        self.assertEqual(list(self.vault.rglob("*")), [])


class TakIsNotASignalGroupTest(_Env):
    async def test_tak_messages_are_not_flagged_as_groups_without_a_branch(self):
        from oden.web_handlers.routing_handlers import _sources

        self.routing["assign"].pop("source:tak")
        item = await self._run(_tak_message(EIGHT_S))
        self.assertFalse(item["unassigned_group"])
        from oden.groups_db import upsert_group

        with unittest.mock.patch("oden.config.SIGNAL_NUMBER", "+46700000000"):
            upsert_group(self.db, "oden-tak-inbound", "TAK Inkommande", account="+46700000000")
            upsert_group(self.db, "g1", "Spaning", account="+46700000000")
            keys = [s["key"] for s in _sources(self.routing, {})]
        self.assertIn("group:Spaning", keys)
        self.assertNotIn("group:TAK Inkommande", keys)
