import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from oden.config_db import init_db
from oden.messages_db import STATUS_FAILED, STATUS_PROCESSED, create_raw_message, get_message_detail
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.pipelines_db import get_events_for_run, get_runs_for_message


class _FailingPipeline:
    name = "failing"

    async def run(self, *, msg_data, reader, writer):
        del msg_data, reader, writer
        raise RuntimeError("boom")


class _HandlingPipeline:
    name = "handling"

    async def run(self, *, msg_data, reader, writer):
        del msg_data, reader, writer
        return True


class _SkippingPipeline:
    name = "skipping"

    async def run(self, *, msg_data, reader, writer):
        del msg_data, reader, writer
        return False


class _WarningPipeline:
    name = "warning"

    async def run(self, *, msg_data, reader, writer):
        del msg_data, reader, writer
        self.last_warnings = [{"message": "non-canonical sagesman", "field": "sagesman", "value": "2A GRUPP"}]
        return True


def _step_runs(db_path, message_id):
    """Pipeline runs without the vägval (router) run that starts every attempt."""
    return [r for r in get_runs_for_message(db_path, message_id) if r["pipeline_name"] != "router"]


class TestPipelineOrchestrator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Routing derived from the (patched) legacy settings, never a real config.db's.
        routing_patch = patch("oden.pipeline_orchestrator.cfg.ROUTING", None)
        routing_patch.start()
        self.addCleanup(routing_patch.stop)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            self.db_path = Path(tmp.name)
        self.db_path.unlink(missing_ok=True)
        init_db(self.db_path)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def _create_sample_message(self) -> int:
        msg_data = {
            "envelope": {
                "sourceNumber": "+46701111111",
                "sourceName": "Test",
                "timestamp": 1710000000000,
                "dataMessage": {
                    "message": "hej",
                    "groupV2": {"id": "grp-1", "name": "Test Group"},
                },
            }
        }
        return create_raw_message(self.db_path, "+46700000000", msg_data)

    async def test_run_message_crash_marks_failed_but_keeps_raw_payload(self):
        message_id = self._create_sample_message()
        orchestrator = PipelineOrchestrator(self.db_path)
        orchestrator._build_pipelines = lambda *_: [_FailingPipeline()]  # type: ignore[method-assign]

        await orchestrator.run_message(
            message_id=message_id,
            msg_data={"envelope": {"dataMessage": {"message": "hej"}}},
            reader=None,
            writer=None,
        )

        detail = get_message_detail(self.db_path, message_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["status"], STATUS_FAILED)
        self.assertIsInstance(detail["envelope_raw"], dict)

        runs = _step_runs(self.db_path, message_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("boom", runs[0]["error_message"] or "")

        events = get_events_for_run(self.db_path, runs[0]["id"])
        event_types = [event["event_type"] for event in events]
        self.assertIn("pipeline_started", event_types)
        self.assertIn("pipeline_failed", event_types)

    async def test_run_message_continues_after_pipeline_failure(self):
        message_id = self._create_sample_message()
        orchestrator = PipelineOrchestrator(self.db_path)
        orchestrator._build_pipelines = lambda *_: [_FailingPipeline(), _SkippingPipeline(), _HandlingPipeline()]  # type: ignore[method-assign]

        await orchestrator.run_message(
            message_id=message_id,
            msg_data={"envelope": {"dataMessage": {"message": "hej"}}},
            reader=None,
            writer=None,
        )

        detail = get_message_detail(self.db_path, message_id)
        self.assertEqual(detail["status"], STATUS_PROCESSED)

        runs = _step_runs(self.db_path, message_id)
        self.assertEqual(len(runs), 3)
        self.assertEqual([run["status"] for run in runs], ["failed", "skipped", "done"])

    async def test_reprocess_twice_keeps_single_raw_message(self):
        message_id = self._create_sample_message()
        orchestrator = PipelineOrchestrator(self.db_path)
        orchestrator._build_pipelines = lambda *_: [_HandlingPipeline()]  # type: ignore[method-assign]

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM raw_messages")
            before_count = cursor.fetchone()[0]
        finally:
            conn.close()

        first = await orchestrator.reprocess(message_id=message_id, reader=None, writer=None)
        second = await orchestrator.reprocess(message_id=message_id, reader=None, writer=None)

        self.assertTrue(first)
        self.assertTrue(second)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM raw_messages")
            after_count = cursor.fetchone()[0]
        finally:
            conn.close()

        routers = [r for r in get_runs_for_message(self.db_path, message_id) if r["pipeline_name"] == "router"]
        self.assertEqual(len(routers), 2, "each attempt starts with its own vägval")
        self.assertEqual(before_count, 1)
        self.assertEqual(after_count, 1)

        runs = _step_runs(self.db_path, message_id)
        self.assertEqual(len(runs), 2)
        self.assertTrue(all(run["status"] == "done" for run in runs))

        detail = get_message_detail(self.db_path, message_id)
        self.assertEqual(detail["status"], STATUS_PROCESSED)

    async def test_reprocess_returns_false_for_missing_message(self):
        orchestrator = PipelineOrchestrator(self.db_path)
        result = await orchestrator.reprocess(message_id=999999, reader=None, writer=None)
        self.assertFalse(result)

    async def test_run_message_persists_pipeline_warning_events(self):
        message_id = self._create_sample_message()
        orchestrator = PipelineOrchestrator(self.db_path)
        orchestrator._build_pipelines = lambda *_: [_WarningPipeline()]  # type: ignore[method-assign]

        await orchestrator.run_message(
            message_id=message_id,
            msg_data={"envelope": {"dataMessage": {"message": "hej"}}},
            reader=None,
            writer=None,
        )

        runs = _step_runs(self.db_path, message_id)
        self.assertEqual(len(runs), 1)

        events = get_events_for_run(self.db_path, runs[0]["id"])
        warning_events = [event for event in events if event["event_type"] == "pipeline_warning"]
        self.assertEqual(len(warning_events), 1)
        self.assertEqual(warning_events[0]["details"]["field"], "sagesman")
        self.assertEqual(warning_events[0]["details"]["value"], "2A GRUPP")

    async def test_build_pipelines_defaults_include_fors_after_seven_s(self):
        orchestrator = PipelineOrchestrator(self.db_path)

        with patch("oden.pipeline_orchestrator.cfg.ENABLED_PIPELINES", []):
            pipelines = orchestrator._build_pipelines()

        # group_filter is no longer a step: it became the vägval before the branch.
        self.assertEqual(
            [pipeline.name for pipeline in pipelines],
            ["tak_text", "seven_s", "fors", "pedars", "scrim", "generic_template"],
        )

    async def test_migration_inserts_new_pipelines_into_an_existing_install(self):
        """An existing install already has a non-empty enabled_pipelines, so a new
        built-in only ever reaches it through _migrate_enabled_pipelines."""
        from oden.config import _migrate_enabled_pipelines

        app_config = {"enabled_pipelines": ["group_filter", "seven_s", "generic_template"]}
        with patch("oden.config_db.set_config_value"):
            _migrate_enabled_pipelines(app_config)

        self.assertEqual(
            app_config["enabled_pipelines"],
            ["group_filter", "seven_s", "fors", "pedars", "scrim", "generic_template"],
        )

    async def test_migration_leaves_an_unconfigured_install_alone(self):
        """An empty list means "not configured yet"; the defaults handle that."""
        from oden.config import _migrate_enabled_pipelines

        app_config = {"enabled_pipelines": []}
        with patch("oden.config_db.set_config_value"):
            _migrate_enabled_pipelines(app_config)
        self.assertEqual(app_config["enabled_pipelines"], [])

    async def test_build_pipelines_prepends_tak_publish_when_publishing_is_on(self):
        orchestrator = PipelineOrchestrator(self.db_path)
        bridge = SimpleNamespace(settings={"publish_reports": True})

        with (
            patch("oden.pipeline_orchestrator.cfg.ENABLED_PIPELINES", ["seven_s"]),
            patch("oden.pipeline_orchestrator.get_tak_bridge", return_value=bridge),
        ):
            pipelines = orchestrator._build_pipelines()

        self.assertEqual(
            [pipeline.name for pipeline in pipelines],
            ["tak_text", "tak_publish", "seven_s", "generic_template"],
        )

    async def test_connected_tak_bridge_does_not_publish_by_default(self):
        """Oden collects from TAK; writing to TAK is opt-in (publish_reports)."""
        from oden.tak.bridge import _DEFAULTS

        orchestrator = PipelineOrchestrator(self.db_path)
        bridge = SimpleNamespace(settings=dict(_DEFAULTS))

        with (
            patch("oden.pipeline_orchestrator.cfg.ENABLED_PIPELINES", ["seven_s"]),
            patch("oden.pipeline_orchestrator.get_tak_bridge", return_value=bridge),
        ):
            names = [pipeline.name for pipeline in orchestrator._build_pipelines()]
            bridge.settings["publish_reports"] = True
            names_after_toggle = [pipeline.name for pipeline in orchestrator._build_pipelines()]

        self.assertEqual(names, ["tak_text", "seven_s", "generic_template"])
        self.assertEqual(names_after_toggle, ["tak_text", "tak_publish", "seven_s", "generic_template"])
